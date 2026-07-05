const { app, BrowserWindow, ipcMain, shell } = require('electron')
const path = require('path')
const fs = require('fs')

let mainWindow = null
let activeWatcher = null

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 680,
    minHeight: 400,
    frame: false,
    autoHideMenuBar: true,
    title: 'LINAR',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  })

  if (!app.isPackaged) {
    mainWindow.loadURL('http://localhost:5173')
  } else {
    mainWindow.loadFile(path.join(__dirname, '../dist/index.html'))
  }

  mainWindow.on('closed', () => { mainWindow = null })
}

// IPC handlers for custom title bar
ipcMain.on('window-minimize', () => mainWindow?.minimize())
ipcMain.on('window-maximize', () => {
  mainWindow?.isMaximized() ? mainWindow.unmaximize() : mainWindow?.maximize()
})
ipcMain.on('window-close', () => mainWindow?.close())

// ── Workspace IPC handlers ─────────────────────────────────
ipcMain.handle('workspace:listFiles', async (_event, dirPath) => {
  try {
    const names = fs.readdirSync(dirPath).sort((a, b) => a.localeCompare(b))
    return names.map(name => {
      const full = path.join(dirPath, name)
      const stat = fs.statSync(full)
      return {
        name,
        path: full,
        size: stat.size,
        mtime: stat.mtimeMs,
        isDir: stat.isDirectory(),
        ext: path.extname(name).toLowerCase(),
      }
    })
  } catch { return [] }
})

ipcMain.handle('workspace:openFile', async (_event, filePath) => {
  return shell.openPath(filePath)
})

ipcMain.handle('workspace:startWatching', async (event, dirPath) => {
  if (activeWatcher) { activeWatcher.close(); activeWatcher = null }
  try {
    activeWatcher = fs.watch(dirPath, (eventType, filename) => {
      if (eventType === 'change' || eventType === 'rename') {
        event.sender.send('workspace:files-changed', { dirPath })
      }
    })
  } catch { /* dir may not exist yet */ }
})

app.whenReady().then(createWindow)

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  if (activeWatcher) { activeWatcher.close(); activeWatcher = null }
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow()
})
