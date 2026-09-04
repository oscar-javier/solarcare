import { useState } from 'react';
import Login from './Login';
import Dashboard from './Dashboard';

function App() {
  const [usuario, setUsuario] = useState(() => {
    const usuarioGuardado = localStorage.getItem('usuario');
    return usuarioGuardado ? JSON.parse(usuarioGuardado) : null;
  });

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('usuario');
    setUsuario(null);
  };

  if (!usuario) {
    return <Login onLoginSuccess={setUsuario} />;
  }

  return <Dashboard usuario={usuario} onLogout={handleLogout} />;
}

export default App;