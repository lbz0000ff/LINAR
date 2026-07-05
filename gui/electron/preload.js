const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('electronAPI', {
  platform: process.platform,
  isElectron: true,
  minimize: () => ipcRenderer.send('window-minimize'),
  maximize: () => ipcRenderer.send('window-maximize'),
  close: () => ipcRenderer.send('window-close'),
  // Workspace file browsing
  listFiles: (dirPath) => ipcRenderer.invoke('workspace:listFiles', dirPath),
  openFile: (filePath) => ipcRenderer.invoke('workspace:openFile', filePath),
  startWatching: (dirPath) => ipcRenderer.invoke('workspace:startWatching', dirPath),
  onFilesChanged: (callback) => {
    ipcRenderer.on('workspace:files-changed', (_event, data) => callback(data))
  },
})
