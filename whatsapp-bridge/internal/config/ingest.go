package config

import "strings"

// Ingest filter modes. The filter decides whether a chat's messages are
// persisted at all; excluded chats never reach the database, so they cannot
// later be read by the MCP server, a stray query, or a compromised tool.
const (
	IngestModeOff       = "off"
	IngestModeAllowlist = "allowlist"
	IngestModeBlocklist = "blocklist"
)

// jidUser returns the user part of a JID ("1555@s.whatsapp.net" -> "1555").
func jidUser(jid string) string {
	if i := strings.IndexByte(jid, '@'); i >= 0 {
		return jid[:i]
	}
	return jid
}

// matchesJID reports whether pattern refers to the same chat as chatJID.
// A pattern may be a full JID ("1555@s.whatsapp.net", "12036@g.us") or a bare
// user part ("1555"). Matching is exact on one of those two forms:
// substring matching is deliberately avoided so that "1555" cannot match
// "91555".
func matchesJID(pattern, chatJID string) bool {
	p := strings.TrimSpace(pattern)
	if p == "" {
		return false
	}
	if strings.EqualFold(p, chatJID) {
		return true
	}
	return strings.EqualFold(jidUser(p), jidUser(chatJID))
}

// matchAny reports whether chatJID matches any configured ingest pattern.
func (c *Config) matchAny(chatJID string) bool {
	for _, p := range c.IngestJIDs {
		if matchesJID(p, chatJID) {
			return true
		}
	}
	return false
}

// ShouldIngest reports whether messages for chatJID may be persisted.
//
// In allowlist mode only listed chats are stored, and an empty list stores
// nothing: a privacy control that is switched on but misconfigured fails
// closed rather than silently recording everything.
func (c *Config) ShouldIngest(chatJID string) bool {
	if c == nil {
		return true
	}
	switch c.IngestMode {
	case IngestModeAllowlist:
		return c.matchAny(chatJID)
	case IngestModeBlocklist:
		return !c.matchAny(chatJID)
	default:
		return true
	}
}
