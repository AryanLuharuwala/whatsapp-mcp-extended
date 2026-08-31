package config

import "testing"

func TestShouldIngest(t *testing.T) {
	tests := []struct {
		name    string
		mode    string
		jids    []string
		chatJID string
		want    bool
	}{
		{"off ingests everything", IngestModeOff, nil, "1555@s.whatsapp.net", true},
		{"off ignores a stale list", IngestModeOff, []string{"1555"}, "1555@s.whatsapp.net", true},

		{"allowlist keeps listed", IngestModeAllowlist, []string{"1555"}, "1555@s.whatsapp.net", true},
		{"allowlist drops unlisted", IngestModeAllowlist, []string{"1555"}, "1999@s.whatsapp.net", false},
		{"allowlist matches full jid", IngestModeAllowlist, []string{"1555@s.whatsapp.net"}, "1555@s.whatsapp.net", true},
		{"allowlist keeps listed group", IngestModeAllowlist, []string{"12036@g.us"}, "12036@g.us", true},
		{"allowlist drops unlisted group", IngestModeAllowlist, []string{"1555"}, "12036@g.us", false},
		{"empty allowlist fails closed", IngestModeAllowlist, nil, "1555@s.whatsapp.net", false},

		{"blocklist drops listed", IngestModeBlocklist, []string{"1555"}, "1555@s.whatsapp.net", false},
		{"blocklist keeps unlisted", IngestModeBlocklist, []string{"1555"}, "1999@s.whatsapp.net", true},
		{"empty blocklist keeps everything", IngestModeBlocklist, nil, "1555@s.whatsapp.net", true},

		// Substring matching would make "1555" swallow "91555" and leak a chat
		// the user never listed. These are the regressions that matter most.
		{"allowlist does not match by suffix", IngestModeAllowlist, []string{"1555"}, "91555@s.whatsapp.net", false},
		{"allowlist does not match by prefix", IngestModeAllowlist, []string{"1555"}, "15551234@s.whatsapp.net", false},
		{"blocklist does not over-block by suffix", IngestModeBlocklist, []string{"1555"}, "91555@s.whatsapp.net", true},

		{"matching is case insensitive", IngestModeAllowlist, []string{"12036@G.US"}, "12036@g.us", true},
		{"blank patterns are ignored", IngestModeAllowlist, []string{"  "}, "1555@s.whatsapp.net", false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			c := &Config{IngestMode: tt.mode, IngestJIDs: tt.jids}
			if got := c.ShouldIngest(tt.chatJID); got != tt.want {
				t.Errorf("ShouldIngest(%q) mode=%s jids=%v = %v, want %v",
					tt.chatJID, tt.mode, tt.jids, got, tt.want)
			}
		})
	}
}

func TestShouldIngestNilConfig(t *testing.T) {
	var c *Config
	if !c.ShouldIngest("1555@s.whatsapp.net") {
		t.Error("nil config must not silently drop messages")
	}
}

func TestSplitJIDs(t *testing.T) {
	got := splitJIDs(" 1555 , ,12036@g.us,")
	want := []string{"1555", "12036@g.us"}
	if len(got) != len(want) {
		t.Fatalf("splitJIDs = %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("splitJIDs[%d] = %q, want %q", i, got[i], want[i])
		}
	}
}
