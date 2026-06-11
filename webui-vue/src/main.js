import { createApp } from 'vue'
import './style.css'
import App from './App.vue'
import { connect } from './composables/useWebSocket.js'

const app = createApp(App)
app.mount('#app')
connect()
