import { useState, useEffect } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import api from './api';

const OPCIONES_CLIMA = [
  { valor: 'clear', etiqueta: '☀️ Despejado' },
  { valor: 'partial_clouds', etiqueta: '⛅ Parcialmente nublado' },
  { valor: 'cloudy', etiqueta: '☁️ Nublado' },
  { valor: 'rain', etiqueta: '🌧️ Lluvia' },
];

function SistemaDetalle({ sistemaId, onVolver }) {
  const [sistema, setSistema] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const [mostrarClima, setMostrarClima] = useState(false);
  const [simulando, setSimulando] = useState(false);
  const [climaSeleccionado, setClimaSeleccionado] = useState(null);
  const [bateria, setBateria] = useState(null);
  const [mostrarFormBateria, setMostrarFormBateria] = useState(false);
  const [capacidadKwh, setCapacidadKwh] = useState('');
  const [fechaInstalacionBateria, setFechaInstalacionBateria] = useState('');
  const [guardandoBateria, setGuardandoBateria] = useState(false);

  const cargarSistema = async () => {
    setCargando(true);
    try {
      const res = await api.get(`/sistemas/${sistemaId}`);
      setSistema(res.data);
    } catch (err) {
      setError('No se pudo cargar el sistema');
    } finally {
      setCargando(false);
    }
  };

  const cargarBateria = async () => {
    try {
      const res = await api.get(`/sistemas/${sistemaId}/bateria`);
      setBateria(res.data);
      setCapacidadKwh(res.data.capacidadKwh.toString());
      setFechaInstalacionBateria(res.data.fechaInstalacion.split('T')[0]);
    } catch (err) {
      if (err.response?.status === 404) {
        setBateria(null);
        setCapacidadKwh('');
        setFechaInstalacionBateria('');
      } else {
        setError('No se pudo cargar la batería');
      }
    }
  };

  useEffect(() => {
    cargarSistema();
    cargarBateria();
  }, [sistemaId]);

  const handleGuardarBateria = async (e) => {
    e.preventDefault();
    setGuardandoBateria(true);
    setError('');

    try {
      const res = await api.post(`/sistemas/${sistemaId}/bateria`, {
        capacidadKwh: parseFloat(capacidadKwh),
        fechaInstalacion: fechaInstalacionBateria,
      });
      setMostrarFormBateria(false);
      await cargarBateria();
    } catch (err) {
      setError(err.response?.data?.error || 'Error al guardar la batería');
    } finally {
      setGuardandoBateria(false);
    }
  };

  const handleSimularDia = async (clima) => {
    setSimulando(true);
    setError('');
    try {
      await api.post(`/sistemas/${sistemaId}/simular-dia`, { clima });
      setClimaSeleccionado(clima);
      cargarSistema(); // recarga para reflejar las lecturas nuevas (ya reemplazadas, no acumuladas)
    } catch (err) {
      setError(err.response?.data?.error || 'Error al simular el día');
    } finally {
      setSimulando(false);
    }
  };

  const datosGrafica = sistema?.lecturas
    ? [...sistema.lecturas]
        .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))
        .map((l) => ({
          hora: new Date(l.timestamp).toLocaleTimeString('es-HN', {
            hour: '2-digit',
            minute: '2-digit',
          }),
          watts: l.watts,
        }))
    : [];

  const etiquetaClimaActual = OPCIONES_CLIMA.find(
    (o) => o.valor === climaSeleccionado
  )?.etiqueta;

  if (cargando) {
    return (
      <div className="min-h-screen bg-slate-900 p-6">
        <p className="text-slate-400">Cargando sistema...</p>
      </div>
    );
  }

  if (!sistema) {
    return (
      <div className="min-h-screen bg-slate-900 p-6">
        <p className="text-red-400">{error || 'Sistema no encontrado'}</p>
        <button onClick={onVolver} className="text-yellow-500 hover:underline mt-4">
          ← Volver
        </button>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-900 p-6">
      <div className="max-w-3xl mx-auto">
        <button
          onClick={onVolver}
          className="text-slate-400 hover:text-white text-sm mb-4"
        >
          ← Volver a mis sistemas
        </button>

        <div className="flex justify-between items-start mb-6">
          <div>
            <h1 className="text-2xl font-bold text-white">{sistema.nombre}</h1>
            <p className="text-slate-400">{sistema.ubicacion}</p>
          </div>
          <div className="text-right">
            <p className="text-yellow-500 font-bold text-lg">
              {sistema.capacidadInstalada} kW
            </p>
            <p className="text-slate-500 text-xs">
              Instalado: {new Date(sistema.fechaInstalacion).toLocaleDateString()}
            </p>
          </div>
        </div>

        <div className="bg-slate-800 p-5 rounded-2xl mb-4">
          <div className="flex justify-between items-start gap-4">
            <div>
              <h2 className="text-white font-semibold">Batería</h2>
              {bateria ? (
                <div className="mt-2">
                  <p className="text-emerald-400 font-bold text-lg">
                    {bateria.capacidadActualKwh} kWh actuales
                  </p>
                  <p className="text-slate-400 text-xs mt-1">
                    De {bateria.capacidadKwh} kWh instalados ·{' '}
                    {Math.round((1 - bateria.factorDegradacion) * 1000) / 10}% de degradación
                  </p>
                  <p className="text-slate-500 text-xs mt-1">
                    Instalada: {new Date(bateria.fechaInstalacion).toLocaleDateString()}
                  </p>
                </div>
              ) : (
                <p className="text-slate-400 text-sm mt-2">No hay una batería registrada.</p>
              )}
            </div>
            <button
              type="button"
              onClick={() => setMostrarFormBateria(!mostrarFormBateria)}
              className="text-xs text-sky-400 hover:underline whitespace-nowrap"
            >
              {mostrarFormBateria ? 'Cancelar' : bateria ? 'Editar batería' : 'Registrar batería'}
            </button>
          </div>

          {mostrarFormBateria && (
            <form onSubmit={handleGuardarBateria} className="mt-4 pt-4 border-t border-slate-700 space-y-3">
              <div className="grid sm:grid-cols-2 gap-3">
                <label className="text-slate-300 text-sm">
                  Capacidad (kWh)
                  <input
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={capacidadKwh}
                    onChange={(e) => setCapacidadKwh(e.target.value)}
                    required
                    className="w-full mt-1 px-3 py-2 rounded-lg bg-slate-700 text-white outline-none focus:ring-2 focus:ring-emerald-500"
                  />
                </label>
                <label className="text-slate-300 text-sm">
                  Fecha de instalación
                  <input
                    type="date"
                    value={fechaInstalacionBateria}
                    onChange={(e) => setFechaInstalacionBateria(e.target.value)}
                    required
                    className="w-full mt-1 px-3 py-2 rounded-lg bg-slate-700 text-white outline-none focus:ring-2 focus:ring-emerald-500"
                  />
                </label>
              </div>
              <button
                type="submit"
                disabled={guardandoBateria}
                className="px-4 py-2 rounded-lg bg-emerald-500 text-slate-900 font-semibold hover:bg-emerald-400 transition text-sm disabled:opacity-50"
              >
                {guardandoBateria ? 'Guardando...' : 'Guardar batería'}
              </button>
            </form>
          )}
        </div>

        <div className="bg-slate-800 p-5 rounded-2xl mb-4">
          <div className="flex justify-between items-center mb-4">
            <div>
              <h2 className="text-white font-semibold">Lecturas del día</h2>
              {etiquetaClimaActual && (
                <p className="text-slate-400 text-xs mt-1">
                  Clima simulado: {etiquetaClimaActual}
                </p>
              )}
            </div>
            <button
              onClick={() => setMostrarClima(!mostrarClima)}
              className="text-xs text-sky-400 hover:underline"
            >
              ☀️ Simular día
            </button>
          </div>

          {mostrarClima && (
            <div className="mb-4 pb-4 border-b border-slate-700">
              <p className="text-slate-300 text-sm mb-2">¿Qué clima quieres simular?</p>
              <div className="flex flex-wrap gap-2">
                {OPCIONES_CLIMA.map((opcion) => {
                  const seleccionado = opcion.valor === climaSeleccionado;
                  return (
                    <button
                      key={opcion.valor}
                      disabled={simulando}
                      onClick={() => handleSimularDia(opcion.valor)}
                      className={`px-3 py-1.5 rounded-lg text-sm transition disabled:opacity-50 ${
                        seleccionado
                          ? 'bg-yellow-500 text-slate-900 font-semibold'
                          : 'bg-slate-700 text-white hover:bg-slate-600'
                      }`}
                    >
                      {opcion.etiqueta}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {error && <p className="text-red-400 text-sm mb-3">{error}</p>}

          {datosGrafica.length === 0 ? (
            <p className="text-slate-400 text-sm">
              Este sistema aún no tiene lecturas. Usa "Simular día" para generar datos.
            </p>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={datosGrafica}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="hora" stroke="#94a3b8" fontSize={12} />
                <YAxis
                  stroke="#94a3b8"
                  fontSize={12}
                  label={{ value: 'Watts', angle: -90, position: 'insideLeft', fill: '#94a3b8' }}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#1e293b',
                    border: '1px solid #334155',
                    borderRadius: '8px',
                    color: '#fff',
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="watts"
                  stroke="#eab308"
                  strokeWidth={2}
                  dot={{ fill: '#eab308' }}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>
    </div>
  );
}

export default SistemaDetalle;