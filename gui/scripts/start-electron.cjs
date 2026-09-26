// Electron launcher — unsets ELECTRON_RUN_AS_NODE before launching
// This is needed because the user's system has ELECTRON_RUN_AS_NODE=1 globally,
// which prevents Electron from entering browser mode.
const { spawn } = require('child_process')
const electron = require('electron') // Returns path to electron binary
const waitOn = require('wait-on')

// Delete the problematic env var for the child process
const env = { ...process.env }
delete env.ELECTRON_RUN_AS_NODE

const frontendOrigin = env.LINAR_GUI_ORIGIN || 'http://127.0.0.1:5173'

waitOn({ resources: [frontendOrigin], timeout: 120000 })
  .then(() => {
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
  })
  .catch((error) => {
    console.error(`Vite did not become ready at ${frontendOrigin}:`, error.message)
    process.exit(1)
  })
