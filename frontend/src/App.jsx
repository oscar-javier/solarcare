import { useState } from 'react';
import Login from './Login';
import Dashboard from './Dashboard';
import SistemaDetalle from './SistemaDetalle';

function App() {
  const [usuario, setUsuario] = useState(() => {
    const usuarioGuardado = localStorage.getItem('usuario');
    return usuarioGuardado ? JSON.parse(usuarioGuardado) : null;
  });
  const [sistemaSimulando, setSistemaSimulando] = useState(null);

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('usuario');
    setUsuario(null);
    setSistemaSimulando(null);
  };

  if (!usuario) {
    return <Login onLoginSuccess={setUsuario} />;
  }

  if (sistemaSimulando) {
    return (
      <SistemaDetalle
        sistemaId={sistemaSimulando}
        onVolver={() => setSistemaSimulando(null)}
      />
    );
  }

  return (
    <Dashboard
      usuario={usuario}
      onLogout={handleLogout}
      onIrASimular={setSistemaSimulando}
    />
  );
}

export default App;