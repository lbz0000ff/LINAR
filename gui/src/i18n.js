import { createI18n } from 'vue-i18n'
import zh from './locales/zh.json'
import en from './locales/en.json'

const savedLocale = localStorage.getItem('linar:locale')
const i18n = createI18n({
  legacy: false,
  locale: savedLocale || 'zh',
  fallbackLocale: 'en',
  messages: { zh, en },
})

// After app mounts, try fetching backend config locale
// as fallback if user never set a preference via settings.
if (!savedLocale) {
  fetch('/config/json')
    .then(r => r.ok ? r.json() : null)
    .then(cfg => {
      if (cfg && cfg.locale && ['zh', 'en'].includes(cfg.locale)) {
        i18n.global.locale.value = cfg.locale
      }
    })
    .catch(() => { /* ignore — offline or no backend */ })
}

export default i18n
