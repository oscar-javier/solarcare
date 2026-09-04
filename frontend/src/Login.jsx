import { useState } from 'react'
import api from './api'

function Login({ onLoginSuccess }) {
  const [modo, setModo] = useState('login')
  const [nombre, setNombre] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [cargando, setCargando] = useState(false)

  const handleSubmit = async (event) => {
    event.preventDefault()
    setError('')
    setCargando(true)

    try {
      if (modo === 'registro') {
        await api.post('/auth/register', { nombre, email, password })
        const response = await api.post('/auth/login', { email, password })
        localStorage.setItem('token', response.data.token)
        localStorage.setItem('usuario', JSON.stringify(response.data.usuario))
        onLoginSuccess(response.data.usuario)
      } else {
        const response = await api.post('/auth/login', { email, password })
        localStorage.setItem('token', response.data.token)
        localStorage.setItem('usuario', JSON.stringify(response.data.usuario))
        onLoginSuccess(response.data.usuario)
      }
    } catch (requestError) {
      setError(
        requestError.response?.data?.error ||
          'Ocurrio un error. Intenta de nuevo.',
      )
    } finally {
      setCargando(false)
    }
  }

  const cambiarModo = () => {
    setModo(modo === 'login' ? 'registro' : 'login')
    setError('')
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-900 px-4">
      <section className="w-full max-w-sm rounded-2xl bg-slate-800 p-8 shadow-xl">
        <h1 className="mb-1 text-center text-3xl font-bold text-white">
          SolarCare
        </h1>
        <p className="mb-6 text-center text-slate-400">
          {modo === 'login'
            ? 'Inicia sesion en tu cuenta'
            : 'Crea una cuenta nueva'}
        </p>

        <form onSubmit={handleSubmit} className="space-y-4">
          {modo === 'registro' && (
            <label className="block">
              <span className="sr-only">Nombre</span>
              <input
                type="text"
                placeholder="Nombre"
                value={nombre}
                onChange={(event) => setNombre(event.target.value)}
                required
                className="w-full rounded-lg bg-slate-700 px-4 py-2 text-white outline-none placeholder:text-slate-400 focus:ring-2 focus:ring-yellow-500"
              />
            </label>
          )}

          <label className="block">
            <span className="sr-only">Correo electronico</span>
            <input
              type="email"
              placeholder="Correo electronico"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
              className="w-full rounded-lg bg-slate-700 px-4 py-2 text-white outline-none placeholder:text-slate-400 focus:ring-2 focus:ring-yellow-500"
            />
          </label>

          <label className="block">
            <span className="sr-only">Contrasena</span>
            <input
              type="password"
              placeholder="Contrasena"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              className="w-full rounded-lg bg-slate-700 px-4 py-2 text-white outline-none placeholder:text-slate-400 focus:ring-2 focus:ring-yellow-500"
            />
          </label>

          {error && <p className="text-center text-sm text-red-400">{error}</p>}

          <button
            type="submit"
            disabled={cargando}
            className="w-full rounded-lg bg-yellow-500 py-2 font-semibold text-slate-900 transition hover:bg-yellow-400 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {cargando
              ? 'Cargando...'
              : modo === 'login'
                ? 'Iniciar sesion'
                : 'Registrarme'}
          </button>
        </form>

        <p className="mt-4 text-center text-sm text-slate-400">
          {modo === 'login' ? 'No tienes cuenta?' : 'Ya tienes cuenta?'}{' '}
          <button
            type="button"
            onClick={cambiarModo}
            className="text-yellow-500 hover:underline"
          >
            {modo === 'login' ? 'Registrate' : 'Inicia sesion'}
          </button>
        </p>
      </section>
    </main>
  )
}

export default Login
