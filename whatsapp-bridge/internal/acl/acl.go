// Package acl holds the chat access policy that decides which conversations
// the bridge is allowed to persist.
//
// The policy lives in a file outside the repository and outside any directory
// exposed to the model through an MCP filesystem server, so the model can
// neither read the policy nor edit it. Only the operator, through the control
// panel, writes this file; the bridge only ever reads it.
package acl

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

// Policy modes.
const (
	ModeOff       = "off"
	ModeAllowlist = "allowlist"
	ModeBlocklist = "blocklist"
)

// Policy is the operator-controlled access policy as stored on disk.
type Policy struct {
	Mode      string   `json:"mode"`
	JIDs      []string `json:"jids"`
	UpdatedAt string   `json:"updated_at,omitempty"`
}

// Chat is a roster entry. It records that a conversation exists so the control
// panel can offer it, and deliberately holds no message content: a chat the
// policy excludes contributes a name and a timestamp here and nothing more.
type Chat struct {
	JID      string `json:"jid"`
	Name     string `json:"name"`
	IsGroup  bool   `json:"is_group"`
	LastSeen string `json:"last_seen"`
	Messages int64  `json:"messages"`
}

// Store loads the policy, tracks the roster, and reloads the policy when the
// file changes so the control panel takes effect without a bridge restart.
type Store struct {
	dir string

	mu        sync.RWMutex
	policy    Policy
	policyMod time.Time
	roster    map[string]*Chat
	dirty     bool
}

// DefaultDir returns the policy directory, overridable with WHATSAPP_ACL_DIR.
// It defaults outside the working tree so that a filesystem MCP server scoped
// to a project directory cannot reach it.
func DefaultDir() string {
	if d := strings.TrimSpace(os.Getenv("WHATSAPP_ACL_DIR")); d != "" {
		return d
	}
	if home, err := os.UserHomeDir(); err == nil {
		return filepath.Join(home, ".config", "whatsapp-mcp")
	}
	return ".whatsapp-mcp"
}

func (s *Store) policyPath() string { return filepath.Join(s.dir, "access.json") }
func (s *Store) rosterPath() string { return filepath.Join(s.dir, "roster.json") }

// New creates a store rooted at dir and loads any existing state.
func New(dir string) (*Store, error) {
	if err := os.MkdirAll(dir, 0o700); err != nil {
		return nil, err
	}
	s := &Store{dir: dir, roster: map[string]*Chat{}}
	s.policy = Policy{Mode: ModeOff}
	s.loadPolicy()
	s.loadRoster()
	return s, nil
}

// Policy returns a copy of the current policy.
func (s *Store) Policy() Policy {
	s.mu.RLock()
	defer s.mu.RUnlock()
	p := s.policy
	p.JIDs = append([]string(nil), p.JIDs...)
	return p
}

// HasPolicyFile reports whether an operator policy exists on disk. When it does
// not, the caller falls back to environment configuration.
func (s *Store) HasPolicyFile() bool {
	_, err := os.Stat(s.policyPath())
	return err == nil
}

// loadPolicy reads the policy file if it changed since the last read.
func (s *Store) loadPolicy() {
	fi, err := os.Stat(s.policyPath())
	if err != nil {
		return
	}
	s.mu.RLock()
	unchanged := fi.ModTime().Equal(s.policyMod)
	s.mu.RUnlock()
	if unchanged {
		return
	}
	data, err := os.ReadFile(s.policyPath())
	if err != nil {
		return
	}
	var p Policy
	if err := json.Unmarshal(data, &p); err != nil {
		// A malformed policy must not silently widen access. Keep the policy
		// already in memory rather than falling back to "allow everything".
		return
	}
	switch p.Mode {
	case ModeAllowlist, ModeBlocklist, ModeOff:
	default:
		p.Mode = ModeAllowlist
	}
	s.mu.Lock()
	s.policy = p
	s.policyMod = fi.ModTime()
	s.mu.Unlock()
}

// Reload re-reads the policy file if it has changed on disk.
func (s *Store) Reload() { s.loadPolicy() }

// jidUser returns the user part of a JID ("1555@s.whatsapp.net" -> "1555").
func jidUser(jid string) string {
	if i := strings.IndexByte(jid, '@'); i >= 0 {
		return jid[:i]
	}
	return jid
}

// matches reports whether pattern names the same chat as chatJID. Matching is
// exact on the full JID or on the user part; substring matching is avoided so
// that "1555" cannot match "91555".
func matches(pattern, chatJID string) bool {
	p := strings.TrimSpace(pattern)
	if p == "" {
		return false
	}
	if strings.EqualFold(p, chatJID) {
		return true
	}
	return strings.EqualFold(jidUser(p), jidUser(chatJID))
}

// Allowed reports whether messages for chatJID may be persisted.
//
// An allowlist that is set but empty allows nothing: a policy that is switched
// on but misconfigured fails closed rather than exposing every conversation.
func (s *Store) Allowed(chatJID string) bool {
	s.mu.RLock()
	defer s.mu.RUnlock()
	found := false
	for _, p := range s.policy.JIDs {
		if matches(p, chatJID) {
			found = true
			break
		}
	}
	switch s.policy.Mode {
	case ModeAllowlist:
		return found
	case ModeBlocklist:
		return !found
	default:
		return true
	}
}

// NoteChat records that a conversation exists, so the control panel can list
// it even while the policy excludes it. Only metadata is kept.
func (s *Store) NoteChat(jid, name string, isGroup bool) {
	if jid == "" {
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	c, ok := s.roster[jid]
	if !ok {
		c = &Chat{JID: jid, IsGroup: isGroup}
		s.roster[jid] = c
	}
	if name != "" {
		c.Name = name
	}
	c.IsGroup = isGroup
	c.LastSeen = time.Now().UTC().Format(time.RFC3339)
	c.Messages++
	s.dirty = true
}

// loadRoster reads a previously persisted roster.
func (s *Store) loadRoster() {
	data, err := os.ReadFile(s.rosterPath())
	if err != nil {
		return
	}
	var chats []*Chat
	if err := json.Unmarshal(data, &chats); err != nil {
		return
	}
	s.mu.Lock()
	for _, c := range chats {
		if c != nil && c.JID != "" {
			s.roster[c.JID] = c
		}
	}
	s.mu.Unlock()
}

// FlushRoster atomically writes the roster if it changed.
func (s *Store) FlushRoster() error {
	s.mu.Lock()
	if !s.dirty {
		s.mu.Unlock()
		return nil
	}
	chats := make([]*Chat, 0, len(s.roster))
	for _, c := range s.roster {
		cp := *c
		chats = append(chats, &cp)
	}
	s.dirty = false
	s.mu.Unlock()

	sort.Slice(chats, func(i, j int) bool { return chats[i].LastSeen > chats[j].LastSeen })
	data, err := json.MarshalIndent(chats, "", "  ")
	if err != nil {
		return err
	}
	tmp := s.rosterPath() + ".tmp"
	if err := os.WriteFile(tmp, data, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, s.rosterPath())
}

// Run reloads the policy and flushes the roster until ctx is done.
func (s *Store) Run(done <-chan struct{}) {
	t := time.NewTicker(2 * time.Second)
	defer t.Stop()
	for {
		select {
		case <-done:
			_ = s.FlushRoster()
			return
		case <-t.C:
			s.Reload()
			_ = s.FlushRoster()
		}
	}
}

// RosterList returns a copy of the known conversations, most recent first.
func (s *Store) RosterList() []*Chat {
	s.mu.RLock()
	defer s.mu.RUnlock()
	out := make([]*Chat, 0, len(s.roster))
	for _, c := range s.roster {
		cp := *c
		out = append(out, &cp)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].LastSeen > out[j].LastSeen })
	return out
}
