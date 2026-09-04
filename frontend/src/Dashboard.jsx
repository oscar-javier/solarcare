import { useState, useEffect } from 'react';
import api from './api';
import SistemaDetalle from './SistemaDetalle';

const OPCIONES_CLIMA = [
  { valor: 'clear', etiqueta: '☀️ Despejado' },
  { valor: 'partial_clouds', etiqueta: '⛅ Parcialmente nublado' },
  { valor: 'cloudy', etiqueta: '☁️ Nublado' },
  { valor: 'rain', etiqueta: '🌧️ Lluvia' },
];

function Dashboard({ usuario, onLogout }) {
  const [sistemas, setSistemas] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [mostrarForm, setMostrarForm] = useState(false);
  const [editandoId, setEditandoId] = useState(null);
  const [error, setError] = useState('');
  const [sistemaSeleccionado, setSistemaSeleccionado] = useState(null);

  const [nombre, setNombre] = useState('');
  const [ubicacion, setUbicacion] = useState('');
  const [capacidadInstalada, setCapacidadInstalada] = useState('');
  const [fechaInstalacion, setFechaInstalacion] = useState('');

  // Estado para el selector de clima de "Simular día"
  const [simulandoId, setSimulandoId] = useState(null); // id del sistema con el selector abierto
  const [cargandoSimulacion, setCargandoSimulacion] = useState(false);
  const [mensajeSimulacion, setMensajeSimulacion] = useState('');

  const cargarSistemas = async () => {
    setCargando(true);
    try {
      const res = await api.get('/sistemas');
      setSistemas(res.data);
    } catch (err) {
      setError('No se pudieron cargar los sistemas');
    } finally {
      setCargando(false);
    }
  };

  useEffect(() => {
    cargarSistemas();
  }, []);

  const limpiarFormulario = () => {
    setNombre('');
    setUbicacion('');
    setCapacidadInstalada('');
    setFechaInstalacion('');
    setEditandoId(null);
    setMostrarForm(false);
  };

  const handleNuevoClick = () => {
    if (mostrarForm && editandoId === null) {
      limpiarFormulario();
    } else {
      limpiarFormulario();
      setMostrarForm(true);
    }
  };

  const handleEditarClick = (sistema) => {
    setNombre(sistema.nombre);
    setUbicacion(sistema.ubicacion);
    setCapacidadInstalada(sistema.capacidadInstalada.toString());
    setFechaInstalacion(sistema.fechaInstalacion.split('T')[0]);
    setEditandoId(sistema.id);
    setMostrarForm(true);
  };

  const handleEliminar = async (id, nombreSistema) => {
    const confirmado = window.confirm(
      `¿Seguro que quieres eliminar "${nombreSistema}"? Esta acción no se puede deshacer.`
    );
    if (!confirmado) return;

    try {
      await api.delete(`/sistemas/${id}`);
      cargarSistemas();
    } catch (err) {
      setError(err.response?.data?.error || 'Error al eliminar el sistema');
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    try {
      const datos = {
        nombre,
        ubicacion,
        capacidadInstalada: parseFloat(capacidadInstalada),
        fechaInstalacion,
      };

      if (editandoId !== null) {
        await api.put(`/sistemas/${editandoId}`, datos);
      } else {
        await api.post('/sistemas', datos);
      }

      limpiarFormulario();
      cargarSistemas();
    } catch (err) {
      setError(
        err.response?.data?.error ||
          `Error al ${editandoId !== null ? 'actualizar' : 'crear'} el sistema`
      );
    }
  };

  const handleSimularDia = async (sistemaId, clima) => {
    setCargandoSimulacion(true);
    setMensajeSimulacion('');
    setError('');
    try {
      const res = await api.post(`/sistemas/${sistemaId}/simular-dia`, { clima });
      setMensajeSimulacion(res.data.mensaje);
      setSimulandoId(null);
    } catch (err) {
      setError(err.response?.data?.error || 'Error al simular el día');
    } finally {
      setCargandoSimulacion(false);
    }
  };

  if (sistemaSeleccionado) {
    return (
      <SistemaDetalle
        sistemaId={sistemaSeleccionado}
        onVolver={() => setSistemaSeleccionado(null)}
      />
    );
  }

  return (
    <div className="min-h-screen bg-slate-900 p-6">
      <div className="max-w-3xl mx-auto">
        <div className="flex justify-between items-center mb-8">
          <div>
            <h1 className="text-2xl font-bold text-white">SolarCare 🌞</h1>
            <p className="text-slate-400 text-sm">Hola, {usuario.nombre}</p>
          </div>
          <button
            onClick={onLogout}
            className="text-slate-400 hover:text-white text-sm"
          >
            Cerrar sesión
          </button>
        </div>

        <div className="flex justify-between items-center mb-4">
          <h2 className="text-lg font-semibold text-white">Tus sistemas solares</h2>
          <button
            onClick={handleNuevoClick}
            className="px-4 py-2 rounded-lg bg-yellow-500 text-slate-900 font-semibold hover:bg-yellow-400 transition text-sm"
          >
            {mostrarForm ? 'Cancelar' : '+ Nuevo sistema'}
          </button>
        </div>

        {mostrarForm && (
          <form
            onSubmit={handleSubmit}
            className="bg-slate-800 p-6 rounded-2xl mb-6 space-y-3"
          >
            <p className="text-slate-300 text-sm font-medium mb-1">
              {editandoId !== null ? 'Editando sistema' : 'Nuevo sistema'}
            </p>
            <input
              type="text"
              placeholder="Nombre (ej. Casa Principal)"
              value={nombre}
              onChange={(e) => setNombre(e.target.value)}
              required
              className="w-full px-4 py-2 rounded-lg bg-slate-700 text-white placeholder-slate-400 outline-none focus:ring-2 focus:ring-yellow-500"
            />
            <input
              type="text"
              placeholder="Ubicación (ej. San Pedro Sula)"
              value={ubicacion}
              onChange={(e) => setUbicacion(e.target.value)}
              required
              className="w-full px-4 py-2 rounded-lg bg-slate-700 text-white placeholder-slate-400 outline-none focus:ring-2 focus:ring-yellow-500"
            />
            <input
              type="number"
              step="0.1"
              placeholder="Capacidad instalada (kW)"
              value={capacidadInstalada}
              onChange={(e) => setCapacidadInstalada(e.target.value)}
              required
              className="w-full px-4 py-2 rounded-lg bg-slate-700 text-white placeholder-slate-400 outline-none focus:ring-2 focus:ring-yellow-500"
            />
            <input
              type="date"
              value={fechaInstalacion}
              onChange={(e) => setFechaInstalacion(e.target.value)}
              required
              className="w-full px-4 py-2 rounded-lg bg-slate-700 text-white outline-none focus:ring-2 focus:ring-yellow-500"
            />
            <button
              type="submit"
              className="w-full py-2 rounded-lg bg-yellow-500 text-slate-900 font-semibold hover:bg-yellow-400 transition"
            >
              {editandoId !== null ? 'Guardar cambios' : 'Guardar sistema'}
            </button>
          </form>
        )}

        {error && <p className="text-red-400 text-sm mb-4">{error}</p>}
        {mensajeSimulacion && (
          <p className="text-green-400 text-sm mb-4">✅ {mensajeSimulacion}</p>
        )}

        {cargando ? (
          <p className="text-slate-400">Cargando sistemas...</p>
        ) : sistemas.length === 0 ? (
          <p className="text-slate-400">
            Aún no tienes sistemas registrados. Crea el primero arriba.
          </p>
        ) : (
          <div className="grid gap-4">
            {sistemas.map((sistema) => (
              <div
                key={sistema.id}
                className="bg-slate-800 p-5 rounded-2xl"
              >
                <div className="flex justify-between items-center">
                  <div>
                    <h3 className="text-white font-semibold">{sistema.nombre}</h3>
                    <p className="text-slate-400 text-sm">{sistema.ubicacion}</p>
                    <div className="flex gap-3 mt-2">
                      <button
                        onClick={() => handleEditarClick(sistema)}
                        className="text-xs text-yellow-500 hover:underline"
                      >
                        Editar
                      </button>
                      <button
                        onClick={() => handleEliminar(sistema.id, sistema.nombre)}
                        className="text-xs text-red-400 hover:underline"
                      >
                        Eliminar
                      </button>
                      <button
                        onClick={() => setSistemaSeleccionado(sistema.id)}
                        className="text-xs text-emerald-400 hover:underline"
                      >
                        Ver detalles
                      </button>
                      <button
                        onClick={() =>
                          setSimulandoId(simulandoId === sistema.id ? null : sistema.id)
                        }
                        className="text-xs text-sky-400 hover:underline"
                      >
                        ☀️ Simular día
                      </button>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="text-yellow-500 font-bold">
                      {sistema.capacidadInstalada} kW
                    </p>
                    <p className="text-slate-500 text-xs">
                      Instalado: {new Date(sistema.fechaInstalacion).toLocaleDateString()}
                    </p>
                  </div>
                </div>

                {simulandoId === sistema.id && (
                  <div className="mt-4 pt-4 border-t border-slate-700">
                    <p className="text-slate-300 text-sm mb-2">
                      ¿Qué clima quieres simular?
                    </p>
                    <div className="flex flex-wrap gap-2">
                      {OPCIONES_CLIMA.map((opcion) => (
                        <button
                          key={opcion.valor}
                          disabled={cargandoSimulacion}
                          onClick={() => handleSimularDia(sistema.id, opcion.valor)}
                          className="px-3 py-1.5 rounded-lg bg-slate-700 text-white text-sm hover:bg-slate-600 transition disabled:opacity-50"
                        >
                          {opcion.etiqueta}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default Dashboard;