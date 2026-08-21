import { useState } from 'react'
import Login from './Login'

function App() {
  const [usuario, setUsuario] = useState(null)

  if (!usuario) {
    return <Login onLoginSuccess={setUsuario} />
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-900 px-4">
      <div className="text-center">
        <h1 className="mb-2 text-3xl font-bold text-white">
          Bienvenido, {usuario.nombre}!
        </h1>
        <p className="text-slate-400">Dashboard proximamente...</p>
      </div>
    </div>
  )
}

export default App
