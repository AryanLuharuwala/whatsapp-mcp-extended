package acl

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func newStore(t *testing.T, p *Policy) *Store {
	t.Helper()
	dir := t.TempDir()
	if p != nil {
		data, err := json.Marshal(p)
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(dir, "access.json"), data, 0o600); err != nil {
			t.Fatal(err)
		}
	}
	s, err := New(dir)
	if err != nil {
		t.Fatal(err)
	}
	return s
}

func TestAllowed(t *testing.T) {
	tests := []struct {
		name    string
		policy  Policy
		chatJID string
		want    bool
	}{
		{"off allows all", Policy{Mode: ModeOff}, "1555@s.whatsapp.net", true},
		{"allowlist keeps listed", Policy{Mode: ModeAllowlist, JIDs: []string{"1555"}}, "1555@s.whatsapp.net", true},
		{"allowlist drops unlisted", Policy{Mode: ModeAllowlist, JIDs: []string{"1555"}}, "1999@s.whatsapp.net", false},
		{"allowlist keeps group", Policy{Mode: ModeAllowlist, JIDs: []string{"12036@g.us"}}, "12036@g.us", true},
		{"empty allowlist fails closed", Policy{Mode: ModeAllowlist}, "1555@s.whatsapp.net", false},
		{"blocklist drops listed", Policy{Mode: ModeBlocklist, JIDs: []string{"1555"}}, "1555@s.whatsapp.net", false},
		{"blocklist keeps unlisted", Policy{Mode: ModeBlocklist, JIDs: []string{"1555"}}, "1999@s.whatsapp.net", true},

		// Substring matching would let "1555" swallow "91555" and expose a chat
		// the operator never listed.
		{"no suffix match", Policy{Mode: ModeAllowlist, JIDs: []string{"1555"}}, "91555@s.whatsapp.net", false},
		{"no prefix match", Policy{Mode: ModeAllowlist, JIDs: []string{"1555"}}, "15551234@s.whatsapp.net", false},
		{"case insensitive", Policy{Mode: ModeAllowlist, JIDs: []string{"12036@G.US"}}, "12036@g.us", true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			s := newStore(t, &tt.policy)
			if got := s.Allowed(tt.chatJID); got != tt.want {
				t.Errorf("Allowed(%q) = %v, want %v", tt.chatJID, got, tt.want)
			}
		})
	}
}

// A policy file that cannot be parsed must not widen access.
func TestMalformedPolicyDoesNotWidenAccess(t *testing.T) {
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "access.json"), []byte("{ not json"), 0o600); err != nil {
		t.Fatal(err)
	}
	s, err := New(dir)
	if err != nil {
		t.Fatal(err)
	}
	// Defaults to an empty allowlist rather than allowing everything.
	if s.Allowed("1555@s.whatsapp.net") && s.Policy().Mode != ModeOff {
		t.Error("malformed policy widened access")
	}
}

// An unknown mode is treated as an allowlist, not as "allow everything".
func TestUnknownModeFailsClosed(t *testing.T) {
	s := newStore(t, &Policy{Mode: "banana", JIDs: []string{"1555"}})
	if s.Allowed("1999@s.whatsapp.net") {
		t.Error("unknown mode allowed an unlisted chat")
	}
	if !s.Allowed("1555@s.whatsapp.net") {
		t.Error("unknown mode should behave as an allowlist for listed chats")
	}
}

func TestHasPolicyFile(t *testing.T) {
	if newStore(t, nil).HasPolicyFile() {
		t.Error("HasPolicyFile true with no file")
	}
	if !newStore(t, &Policy{Mode: ModeOff}).HasPolicyFile() {
		t.Error("HasPolicyFile false with a file present")
	}
}

// The roster records excluded chats so the panel can offer them, and survives
// a round trip through disk.
func TestRosterRoundTrip(t *testing.T) {
	dir := t.TempDir()
	s, err := New(dir)
	if err != nil {
		t.Fatal(err)
	}
	s.NoteChat("12036@g.us", "Team", true)
	s.NoteChat("12036@g.us", "Team", true)
	s.NoteChat("1555@s.whatsapp.net", "Alice", false)
	if err := s.FlushRoster(); err != nil {
		t.Fatal(err)
	}

	s2, err := New(dir)
	if err != nil {
		t.Fatal(err)
	}
	got := map[string]*Chat{}
	for _, c := range s2.RosterList() {
		got[c.JID] = c
	}
	if len(got) != 2 {
		t.Fatalf("roster has %d chats, want 2", len(got))
	}
	if g := got["12036@g.us"]; g == nil || !g.IsGroup || g.Name != "Team" || g.Messages != 2 {
		t.Errorf("group entry wrong: %+v", g)
	}
	if a := got["1555@s.whatsapp.net"]; a == nil || a.IsGroup || a.Name != "Alice" {
		t.Errorf("dm entry wrong: %+v", a)
	}
}
