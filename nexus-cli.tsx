import React, { useState, useEffect } from 'react';
import { render, Text, Box, useApp, useInput } from 'ink';

// --- ATOMIC STATE & TELEMETRY INVARIANTS ---
interface SystemMetrics {
  cpuUsage: number;
  memoryAllocatedMB: number;
  fineStructureAlpha: number;
  activeAgents: number;
  status: 'OPTIMAL' | 'DEGRADED' | 'REBALANCING';
}

interface SwarmAgent {
  id: string;
  role: string;
  loadPct: number;
  status: 'IDLE' | 'EXECUTING' | 'SYNCING';
}

// --- CORE REACTION RUNTIME COMPONENT ---
export const QuantumNexusCLI: React.FC = () => {
  const { exit } = useApp();

  const [metrics, setMetrics] = useState<SystemMetrics>({
    cpuUsage: 12.4,
    memoryAllocatedMB: 64.2,
    fineStructureAlpha: 0.00729735256,
    activeAgents: 4,
    status: 'OPTIMAL',
  });

  const [agents, setAgents] = useState<SwarmAgent[]>([
    { id: 'AGENT-α1', role: 'Arbitrage Engine', loadPct: 18.4, status: 'EXECUTING' },
    { id: 'AGENT-β2', role: 'Pyth Oracle Guard', loadPct: 8.2, status: 'SYNCING' },
    { id: 'AGENT-γ3', role: 'Risk Engine L3', loadPct: 24.1, status: 'EXECUTING' },
    { id: 'AGENT-δ4', role: 'Telemetry Pipeline', loadPct: 4.5, status: 'IDLE' },
  ]);

  // Handle deterministic keybindings
  useInput((input, key) => {
    if (input === 'q' || (key.ctrl && input === 'c')) {
      exit();
    }
  });

  // High-frequency deterministic state update loop
  useEffect(() => {
    const timer = setInterval(() => {
      setMetrics((prev) => ({
        ...prev,
        cpuUsage: Number((10 + Math.random() * 8).toFixed(2)),
        memoryAllocatedMB: Number((60 + Math.random() * 5).toFixed(2)),
      }));

      setAgents((prev) =>
        prev.map((agent) => ({
          ...agent,
          loadPct: Number((Math.random() * 40 + 5).toFixed(1)),
        }))
      );
    }, 250);

    return () => clearInterval(timer);
  }, []);

  return (
    <Box flexDirection="column" padding={1} borderWidth="single" borderColor="cyan">
      {/* HEADER MATRIX */}
      <Box marginBottom={1} justifyContent="space-between">
        <Text bold color="green">
          [QUANTUM NEXUS OS - SOVEREIGN CORE v13.0]
        </Text>
        <Text color="yellow">FINE STRUCTURE: α ≈ {metrics.fineStructureAlpha}</Text>
      </Box>

      {/* SYSTEM TELEMETRY */}
      <Box flexDirection="column" marginBottom={1} paddingX={1} borderWidth="classic" borderColor="gray">
        <Box justifyContent="space-between">
          <Text color="white">System Status: <Text color="green" bold>{metrics.status}</Text></Text>
          <Text color="white">Active Agents: <Text color="magenta">{metrics.activeAgents}</Text></Text>
        </Box>
        <Box justifyContent="space-between">
          <Text color="white">CPU Allocation: <Text color="yellow">{metrics.cpuUsage}%</Text></Text>
          <Text color="white">Memory Footprint: <Text color="cyan">{metrics.memoryAllocatedMB} MB</Text></Text>
        </Box>
      </Box>

      {/* SWARM AGENT MATRIX */}
      <Box flexDirection="column" marginBottom={1}>
        <Text bold underline color="blue">
          ACTIVE SWARM ORCHESTRATION LAYER:
        </Text>
        {agents.map((agent) => (
          <Box key={agent.id} justifyContent="space-between" paddingX={1}>
            <Text color="white">{agent.id} [{agent.role}]</Text>
            <Text color={agent.status === 'EXECUTING' ? 'green' : agent.status === 'SYNCING' ? 'yellow' : 'gray'}>
              {agent.status} ({agent.loadPct}%)
            </Text>
          </Box>
        ))}
      </Box>

      {/* FOOTER CONTROL PROTOCOL */}
      <Box marginTop={1} borderColor="dim" borderWidth="top">
        <Text dimColor>Press 'q' or Ctrl+C to terminate runtime session gracefully.</Text>
      </Box>
    </Box>
  );
};

// --- DETERMINISTIC ENTRYPOINT & CLEANUP HANDLER ---
const main = () => {
  const { waitUntilExit } = render(<QuantumNexusCLI />);

  const cleanup = (signal: string) => {
    process.stdout.write(`\n[NEXUS CORE] Received ${signal}. Executing atomic teardown...\n`);
    process.exit(0);
  };

  process.on('SIGINT', () => cleanup('SIGINT'));
  process.on('SIGTERM', () => cleanup('SIGTERM'));

  waitUntilExit().then(() => {
    process.stdout.write('[NEXUS CORE] Runtime exited cleanly.\n');
  });
};

if (import.meta.url === `file://${process.argv[1]}`) {
  main();
}
