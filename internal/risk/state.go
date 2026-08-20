package risk

import (
	"errors"
	"sync"
	"time"
)

type State string

const (
	GREEN  State = "GREEN"
	YELLOW State = "YELLOW"
	ORANGE State = "ORANGE"
	RED    State = "RED"
)

var (
	ErrInvalidThreshold = errors.New("risk threshold must be positive")
	ErrInvalidCooldown  = errors.New("risk cooldown must be non-negative")
	ErrInvalidState     = errors.New("invalid risk state")
)

type Manager struct {
	mu           sync.RWMutex
	state        State
	failCount    int
	circuitOpen  bool
	circuitUntil time.Time
	threshold    int
	cooldownSec  int
}

func NewManager(threshold, cooldownSec int) *Manager {
	if threshold < 1 {
		threshold = 1
	}
	if cooldownSec < 0 {
		cooldownSec = 0
	}
	return &Manager{state: GREEN, threshold: threshold, cooldownSec: cooldownSec}
}

func (m *Manager) Current() State {
	m.mu.RLock()
	defer m.mu.RUnlock()
	if m.circuitOpen && time.Now().Before(m.circuitUntil) {
		return RED
	}
	return m.state
}

func (m *Manager) AllowNewOrder() bool {
	s := m.Current()
	return s == GREEN || s == YELLOW
}

func (m *Manager) RecordFail() {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.failCount++
	if m.failCount >= m.threshold {
		m.circuitOpen = true
		m.circuitUntil = time.Now().Add(time.Duration(m.cooldownSec) * time.Second)
		m.state = RED
	}
}

func (m *Manager) RecordSuccess() {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.failCount = 0
	if m.circuitOpen && !time.Now().Before(m.circuitUntil) {
		m.circuitOpen = false
		m.state = GREEN
	}
}

func (m *Manager) SetState(s State) error {
	if s != GREEN && s != YELLOW && s != ORANGE && s != RED {
		return ErrInvalidState
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	m.state = s
	if s == RED {
		m.circuitOpen = true
		m.circuitUntil = time.Now().Add(time.Duration(m.cooldownSec) * time.Second)
	}
	return nil
}
