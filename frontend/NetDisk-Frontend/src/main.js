import './assets/main.css'
import './assets/dcp.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { useAuthStore } from './stores/auth'

const app = createApp(App)

app.use(createPinia())
app.use(router)

// The first guard restores the device session before protected views can request data.
router.isReady().then(() => app.mount('#app'))

window.addEventListener('storage', (event) => {
  if (event.key === 'dcp_netdisk_signed_out' && event.newValue) {
    const auth = useAuthStore()
    auth.signedOut = true
    auth.clearSession()
    router.replace('/login')
  }
})
