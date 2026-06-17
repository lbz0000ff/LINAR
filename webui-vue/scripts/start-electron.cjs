// Electron launcher — unsets ELECTRON_RUN_AS_NODE before launching
// This is needed because the user's system has ELECTRON_RUN_AS_NODE=1 globally,
// which prevents Electron from entering browser mode.
const { spawn } = require('child_process')
const electron = require('electron') // Returns path to electron binary

// Delete the problematic env var for the child process
const env = { ...process.env }
delete env.ELECTRON_RUN_AS_NODE

const child = spawn(electron, process.argv.slice(2), {
  stdio: 'inherit',
  env,
})

child.on('close', (code, signal) => {
  if (signal) {
    console.error('Electron exited with signal:', signal)
    process.exit(1)
  }
  process.exit(code ?? 0)
})
