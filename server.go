// Animal Clip Engine - HTTP server
//
// Menyerve halaman statis dari folder app/ dan menangani upload video + JSON,
// menjalankan program-clipper.py / program-single-clip.py sebagai subprocess,
// lalu mengembalikan video hasil sebagai download.
//
// Catatan penting:
//   * Python scripts memakai path relatif (./DynaPuff, ./art, ./output),
//     jadi working directory subprocess di-set ke root repo (parent dari app/).
//   * Output video disimpan di folder <root>/output dengan nama unik, lalu
//     di-stream kembali ke client sebagai download.

package main

import (
	"encoding/json"
	"fmt"
	"io"
	"log"
	"mime/multipart"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

const maxUploadBytes = 2 << 30 // 2 GiB — cukup untuk video panjang

var (
	// rootDir = parent dari lokasi server.go (root repo).
	rootDir   string
	outputDir string
)

func init() {
	exe, err := os.Executable()
	if err != nil {
		log.Fatalf("[FATAL] tidak bisa resolve executable: %v", err)
	}
	// Ketika dijalankan via `go run`, executable berada di temp; fallback ke cwd.
	appDir := filepath.Dir(exe)
	if !fileExists(filepath.Join(appDir, "..", "program-clipper.py")) {
		appDir, _ = os.Getwd()
		appDir = filepath.Join(appDir, "app")
	}
	rootDir = filepath.Clean(filepath.Join(appDir, ".."))
	outputDir = filepath.Join(rootDir, "output")
	os.MkdirAll(outputDir, 0o755)
	log.Printf("[INFO] root repo        : %s", rootDir)
	log.Printf("[INFO] folder output    : %s", outputDir)
}

func fileExists(p string) bool {
	_, err := os.Stat(p)
	return err == nil
}

func main() {
	// Static file server untuk app/
	fs := http.FileServer(http.Dir("."))
	http.Handle("/", noCache(fs))

	http.HandleFunc("/api/clipper", handleClipper)
	http.HandleFunc("/api/single-clip", handleSingleClip)

	addr := ":8080"
	log.Printf("[INFO] server berjalan di http://localhost%s", addr)
	if err := http.ListenAndServe(addr, nil); err != nil {
		log.Fatalf("[FATAL] server: %v", err)
	}
}

func noCache(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		next.ServeHTTP(w, r)
	})
}

// ---------- helper ----------

func writeJSONError(w http.ResponseWriter, status int, msg string) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": msg})
}

func safeFileName(name string) string {
	name = strings.TrimSpace(name)
	if name == "" {
		return "output.mp4"
	}
	name = strings.ReplaceAll(name, "/", "_")
	name = strings.ReplaceAll(name, "\\", "_")
	if !strings.HasSuffix(strings.ToLower(name), ".mp4") {
		name += ".mp4"
	}
	return name
}

// saveUploadedFile menyimpan file yang diupload dari multipart ke folder output,
// mengembalikan path absolut.
func saveUploadedFile(file multipart.File, originalName string) (string, error) {
	name := filepath.Base(originalName)
	if name == "" || name == "." {
		name = fmt.Sprintf("upload_%d.mp4", time.Now().UnixNano())
	}
	dst := filepath.Join(outputDir, name)
	out, err := os.Create(dst)
	if err != nil {
		return "", err
	}
	defer out.Close()
	if _, err := io.Copy(out, file); err != nil {
		return "", err
	}
	return dst, nil
}

// runPython menjalankan script python dengan working directory rootDir,
// mengembalikan gabungan stdout+stderr.
func runPython(args []string) (string, error) {
	cmd := exec.Command("python", args...)
	cmd.Dir = rootDir
	out, err := cmd.CombinedOutput()
	return string(out), err
}

// serveResultFile membersihkan file sementara setelah di-stream.
func serveResultFile(w http.ResponseWriter, path, downloadName string) {
	defer os.Remove(path)
	f, err := os.Open(path)
	if err != nil {
		writeJSONError(w, 500, fmt.Sprintf("Gagal membaca hasil: %v", err))
		return
	}
	defer f.Close()

	info, err := f.Stat()
	if err != nil {
		writeJSONError(w, 500, fmt.Sprintf("Gagal stat hasil: %v", err))
		return
	}

	w.Header().Set("Content-Type", "video/mp4")
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="%s"`, downloadName))
	w.Header().Set("Content-Length", fmt.Sprintf("%d", info.Size()))
	w.WriteHeader(http.StatusOK)
	_, _ = io.Copy(w, f)
}

// ---------- handlers ----------

func handleClipper(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSONError(w, http.StatusMethodNotAllowed, "Method tidak diizinkan.")
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, maxUploadBytes)
	if err := r.ParseMultipartForm(64 << 20); err != nil {
		writeJSONError(w, http.StatusBadRequest, "Gagal membaca upload: "+err.Error())
		return
	}

	file, handler, err := r.FormFile("video")
	if err != nil {
		writeJSONError(w, http.StatusBadRequest, "Field 'video' tidak ditemukan.")
		return
	}
	defer file.Close()

	videoPath, err := saveUploadedFile(file, handler.Filename)
	if err != nil {
		writeJSONError(w, 500, "Gagal menyimpan video: "+err.Error())
		return
	}
	defer os.Remove(videoPath)

	jsonText := r.FormValue("json")
	if strings.TrimSpace(jsonText) == "" {
		writeJSONError(w, http.StatusBadRequest, "Field 'json' kosong.")
		return
	}
	var parsed map[string]any
	if err := json.Unmarshal([]byte(jsonText), &parsed); err != nil {
		writeJSONError(w, http.StatusBadRequest, "JSON tidak valid: "+err.Error())
		return
	}
	if _, ok := parsed["clips"]; !ok {
		writeJSONError(w, http.StatusBadRequest, "JSON harus punya field 'clips'.")
		return
	}

	jsonPath := filepath.Join(outputDir, fmt.Sprintf("clips_%d.json", time.Now().UnixNano()))
	if err := os.WriteFile(jsonPath, []byte(jsonText), 0o644); err != nil {
		writeJSONError(w, 500, "Gagal menulis JSON: "+err.Error())
		return
	}
	defer os.Remove(jsonPath)

	downloadName := safeFileName(r.FormValue("output"))
	outPath := filepath.Join(outputDir, fmt.Sprintf("%d_%s", time.Now().UnixNano(), downloadName))
	defer os.Remove(outPath)

	args := []string{
		"program-clipper.py",
		"--video", videoPath,
		"--json", jsonPath,
		"--output", outPath,
	}
	log.Printf("[CLIPPER] mulai render: %s -> %s", handler.Filename, outPath)
	combined, runErr := runPython(args)
	log.Printf("[CLIPPER] selesai (err=%v)", runErr)

	if runErr != nil {
		writeJSONError(w, 500, "Proses render gagal.\n\n"+combined)
		return
	}
	serveResultFile(w, outPath, downloadName)
}

func handleSingleClip(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSONError(w, http.StatusMethodNotAllowed, "Method tidak diizinkan.")
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, maxUploadBytes)
	if err := r.ParseMultipartForm(64 << 20); err != nil {
		writeJSONError(w, http.StatusBadRequest, "Gagal membaca upload: "+err.Error())
		return
	}

	file, handler, err := r.FormFile("video")
	if err != nil {
		writeJSONError(w, http.StatusBadRequest, "Field 'video' tidak ditemukan.")
		return
	}
	defer file.Close()

	videoPath, err := saveUploadedFile(file, handler.Filename)
	if err != nil {
		writeJSONError(w, 500, "Gagal menyimpan video: "+err.Error())
		return
	}
	defer os.Remove(videoPath)

	title := strings.TrimSpace(r.FormValue("title"))
	if title == "" {
		writeJSONError(w, http.StatusBadRequest, "Field 'title' kosong.")
		return
	}

	downloadName := safeFileName(r.FormValue("output"))
	outPath := filepath.Join(outputDir, fmt.Sprintf("%d_%s", time.Now().UnixNano(), downloadName))
	defer os.Remove(outPath)

	y := strings.TrimSpace(r.FormValue("y"))
	if y == "" {
		y = "60"
	}

	args := []string{
		"program-single-clip.py",
		"--video", videoPath,
		"--title", title,
		"--output", outPath,
		"--y", y,
	}
	log.Printf("[SINGLE] mulai render: %s -> %s", handler.Filename, outPath)
	combined, runErr := runPython(args)
	log.Printf("[SINGLE] selesai (err=%v)", runErr)

	if runErr != nil {
		writeJSONError(w, 500, "Proses render gagal.\n\n"+combined)
		return
	}
	serveResultFile(w, outPath, downloadName)
}
