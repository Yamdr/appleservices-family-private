// prepare-sap-assets caches the pinned public Apple framework files used by SAP.
// It does not open a signing session, authenticate an account, or make purchases.
package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/Laky-64/appleservices/internal/sap/assets"
)

type fileResult struct {
	Name   string `json:"name"`
	Bytes  int    `json:"bytes"`
	SHA256 string `json:"sha256"`
}

type result struct {
	Component string       `json:"component"`
	OK        bool         `json:"ok"`
	Seconds   float64      `json:"seconds"`
	Files     []fileResult `json:"files,omitempty"`
	Error     string       `json:"error,omitempty"`
}

func describe(name string, data []byte) fileResult {
	digest := sha256.Sum256(data)
	return fileResult{Name: name, Bytes: len(data), SHA256: hex.EncodeToString(digest[:])}
}

func prepare(ctx context.Context) error {
	results := make(chan result, 2)
	go func() {
		started := time.Now()
		bundle, err := assets.Load(ctx)
		r := result{Component: "apple-assets-v2", OK: err == nil, Seconds: time.Since(started).Seconds()}
		if err != nil {
			r.Error = err.Error()
		} else {
			r.Files = []fileResult{
				describe("CommerceKit", bundle.CommerceKit),
				describe("CommerceCore", bundle.CommerceCore),
				describe("CoreFP", bundle.CoreFP),
				describe("CoreFP.icxs", bundle.CoreFPICXS),
			}
		}
		results <- r
	}()
	go func() {
		started := time.Now()
		data, err := assets.LoadStoreAgent(ctx)
		r := result{Component: "apple-storeagent-v1", OK: err == nil, Seconds: time.Since(started).Seconds()}
		if err != nil {
			r.Error = err.Error()
		} else {
			r.Files = []fileResult{describe("storeagent", data)}
		}
		results <- r
	}()

	failed := false
	encoder := json.NewEncoder(os.Stdout)
	for range 2 {
		r := <-results
		if err := encoder.Encode(r); err != nil {
			return fmt.Errorf("write preparation result: %w", err)
		}
		failed = failed || !r.OK
	}
	if failed {
		return errors.New("one or more SAP asset groups could not be prepared")
	}
	return nil
}

func run() error {
	timeout := flag.Duration("timeout", 8*time.Minute, "maximum time to prepare both asset groups")
	cacheDir := flag.String("cache-dir", os.Getenv("APPLESERVICES_CACHE_DIR"), "absolute cache directory; defaults to APPLESERVICES_CACHE_DIR")
	flag.Parse()
	if flag.NArg() != 0 {
		return errors.New("unexpected positional arguments")
	}
	if *timeout <= 0 {
		return errors.New("timeout must be positive")
	}
	if !filepath.IsAbs(*cacheDir) {
		return errors.New("set -cache-dir or APPLESERVICES_CACHE_DIR to an absolute directory")
	}
	if strings.EqualFold(filepath.VolumeName(*cacheDir), "C:") {
		return errors.New("choose a cache directory outside C:")
	}
	if err := os.Setenv("APPLESERVICES_CACHE_DIR", filepath.Clean(*cacheDir)); err != nil {
		return fmt.Errorf("set cache directory: %w", err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), *timeout)
	defer cancel()
	return prepare(ctx)
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
