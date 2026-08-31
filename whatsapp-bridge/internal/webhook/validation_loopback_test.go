package webhook

import "testing"

func TestLoopbackExceptionIsNarrow(t *testing.T) {
	tests := []struct {
		name, url string
		allow     bool
		wantErr   bool
	}{
		{"loopback blocked by default", "http://127.0.0.1:8781/", false, true},
		{"loopback allowed when opted in", "http://127.0.0.1:8781/", true, false},
		{"localhost allowed when opted in", "http://localhost:8781/", true, false},

		// The opt-in must not become a general private-network pass. Link-local
		// in particular reaches the cloud metadata endpoint.
		{"metadata IP still blocked", "http://169.254.169.254/", true, true},
		{"metadata host still blocked", "http://metadata.google.internal/", true, true},
		{"rfc1918 still blocked", "http://192.168.1.10/", true, true},
		{"rfc1918 10/8 still blocked", "http://10.0.0.5/", true, true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			t.Setenv("DISABLE_SSRF_CHECK", "")
			if tt.allow {
				t.Setenv("WEBHOOK_ALLOW_LOOPBACK", "true")
			} else {
				t.Setenv("WEBHOOK_ALLOW_LOOPBACK", "")
			}
			err := ValidateWebhookURL(tt.url)
			if (err != nil) != tt.wantErr {
				t.Errorf("ValidateWebhookURL(%q) err=%v, wantErr=%v", tt.url, err, tt.wantErr)
			}
		})
	}
}
