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

const FACTORES_CLIMA = {
  clear: 1.0,
  partial_clouds: 0.7,
  cloudy: 0.4,
  rain: 0.15,
};

// Estado exacto "ahora mismo" (con minutos), igual que en el Dashboard
function calcularEstadoActual(sistema, categoriaClima) {
  const ahora = new Date();
  const horaDecimal = ahora.getHours() + ahora.getMinutes() / 60;

  if (horaDecimal < 6 || horaDecimal > 18) {
    return { generando: false };
  }

  const anguloSolar = Math.PI * ((horaDecimal - 6) / 12);
  const factorSolar = Math.max(0, Math.sin(anguloSolar));
  const factorClima = FACTORES_CLIMA[categoriaClima] ?? FACTORES_CLIMA.clear;

  const TASA_DEGRADACION_ANUAL = 0.006;
  const añosDesdeInstalacion =
    (Date.now() - new Date(sistema.fechaInstalacion).getTime()) /
    (1000 * 60 * 60 * 24 * 365.25);
  const factorDegradacion = Math.max(0, 1 - TASA_DEGRADACION_ANUAL * añosDesdeInstalacion);

  const porcentaje = factorSolar * factorClima * factorDegradacion * 100;
  const watts = sistema.capacidadInstalada * 1000 * (porcentaje / 100);

  return {
    generando: true,
    porcentaje: Math.round(porcentaje * 10) / 10,
    watts: Math.round(watts),
  };
}

function SistemaDetalle({ sistemaId, onVolver }) {
  const [sistema, setSistema] = useState(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState('');
  const [simulando, setSimulando] = useState(false);
  const [climaSeleccionado, setClimaSeleccionado] = useState(null);

  // Batería
  const [bateria, setBateria] = useState(null);
  const [cargandoBateria, setCargandoBateria] = useState(true);
  const [mostrarFormBateria, setMostrarFormBateria] = useState(false);
  const [capacidadKwh, setCapacidadKwh] = useState('');
  const [fechaInstalacionBateria, setFechaInstalacionBateria] = useState('');
  const [errorBateria, setErrorBateria] = useState('');

  // Reloj informativo (no restringe la simulación, solo da contexto)
  const [horaActual, setHoraActual] = useState(new Date());
  useEffect(() => {
    const intervalo = setInterval(() => setHoraActual(new Date()), 60000);
    return () => clearInterval(intervalo);
  }, []);

  // Clima real de hoy, para auto-simular la primera vez y mostrar contexto
  const [climaReal, setClimaReal] = useState(null);

  useEffect(() => {
    const cargarClimaReal = async () => {
      try {
        const res = await api.get('/clima-actual');
        setClimaReal(res.data);
      } catch (err) {
        setClimaReal(null);
      }
    };
    cargarClimaReal();
    const intervalo = setInterval(cargarClimaReal, 10 * 60 * 1000);
    return () => clearInterval(intervalo);
  }, []);

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
    setCargandoBateria(true);
    try {
      const res = await api.get(`/sistemas/${sistemaId}/bateria`);
      setBateria(res.data);
    } catch (err) {
      setBateria(null);
    } finally {
      setCargandoBateria(false);
    }
  };

  useEffect(() => {
    cargarSistema();
    cargarBateria();
  }, [sistemaId]);

  // Si el sistema no tiene ninguna lectura todavía y ya sabemos el clima real,
  // simula automáticamente con ese clima para no obligar al usuario a hacerlo a mano.
  useEffect(() => {
    if (sistema && climaReal && (!sistema.lecturas || sistema.lecturas.length === 0)) {
      handleSimularDia(climaReal.categoria);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sistema, climaReal]);

  const handleSimularDia = async (clima) => {
    setSimulando(true);
    setError('');
    try {
      await api.post(`/sistemas/${sistemaId}/simular-dia`, { clima });
      setClimaSeleccionado(clima);
      cargarSistema();
    } catch (err) {
      setError(err.response?.data?.error || 'Error al simular el día');
    } finally {
      setSimulando(false);
    }
  };

  const handleEditarBateria = () => {
    if (bateria) {
      setCapacidadKwh(bateria.capacidadKwh.toString());
      setFechaInstalacionBateria(bateria.fechaInstalacion.split('T')[0]);
    }
    setMostrarFormBateria(true);
  };

  const handleGuardarBateria = async (e) => {
    e.preventDefault();
    setErrorBateria('');
    try {
      await api.post(`/sistemas/${sistemaId}/bateria`, {
        capacidadKwh: parseFloat(capacidadKwh),
        fechaInstalacion: fechaInstalacionBateria,
      });
      setMostrarFormBateria(false);
      setCapacidadKwh('');
      setFechaInstalacionBateria('');
      cargarBateria();
    } catch (err) {
      setErrorBateria(err.response?.data?.error || 'Error al guardar la batería');
    }
  };

  const handleEliminarBateria = async () => {
    const confirmado = window.confirm(
      '¿Seguro que quieres eliminar la batería de este sistema?'
    );
    if (!confirmado) return;

    try {
      await api.delete(`/sistemas/${sistemaId}/bateria`);
      setBateria(null);
    } catch (err) {
      setErrorBateria(err.response?.data?.error || 'Error al eliminar la batería');
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
          porcentaje:
            Math.round((l.watts / (sistema.capacidadInstalada * 1000)) * 1000) / 10,
        }))
    : [];

  const etiquetaClimaActual = OPCIONES_CLIMA.find(
    (o) => o.valor === climaSeleccionado
  )?.etiqueta;

  const horaActualTexto = horaActual.toLocaleTimeString('es-HN', {
    hour: '2-digit',
    minute: '2-digit',
  });

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
        <div className="flex justify-between items-center mb-4">
          <button
            onClick={onVolver}
            className="text-slate-400 hover:text-white text-sm"
          >
            ← Volver a mis sistemas
          </button>
          <p className="text-slate-500 text-xs">Hora actual: {horaActualTexto}</p>
        </div>

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
          <h2 className="text-white font-semibold mb-1">Simulación (6:00 a. m. – 6:00 p. m.)</h2>
          {etiquetaClimaActual && (
            <p className="text-slate-400 text-xs mb-4">
              Clima simulado: {etiquetaClimaActual}
            </p>
          )}

          {climaReal && (
            <div className="bg-slate-900/60 rounded-xl p-3 mb-4">
              <div className="flex justify-between items-center mb-1">
                <div>
                  <p className="text-slate-400 text-xs">Clima real ahora</p>
                  <p className="text-white text-sm font-semibold">
                    {OPCIONES_CLIMA.find((o) => o.valor === climaReal.categoria)?.etiqueta}{' '}
                    · {climaReal.temperatura}°C
                  </p>
                </div>
                <p className="text-slate-400 text-xs">{horaActualTexto}</p>
              </div>
              {(() => {
                const estado = calcularEstadoActual(sistema, climaReal.categoria);
                return estado.generando ? (
                  <p className="text-yellow-500 text-sm font-semibold text-right">
                    {estado.porcentaje}% · ~{estado.watts} W ahora mismo
                  </p>
                ) : (
                  <p className="text-slate-300 text-sm text-right">
                    🌙 Sin generación (fuera de 6 a.m.–6 p.m.)
                  </p>
                );
              })()}
            </div>
          )}

          <div className="mb-4 pb-4 border-b border-slate-700">
            <p className="text-slate-300 text-sm mb-2">¿Qué clima quieres simular?</p>
            <div className="flex flex-wrap gap-2">
              {OPCIONES_CLIMA.map((opcion) => {
                const seleccionado = opcion.valor === climaSeleccionado;
                const esClimaReal = opcion.valor === climaReal?.categoria;
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
                    {esClimaReal && (
                      <span className="ml-1 text-[10px] opacity-75">(hoy)</span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          {error && <p className="text-red-400 text-sm mb-3">{error}</p>}

          {datosGrafica.length === 0 ? (
            <p className="text-slate-400 text-sm">
              {simulando ? 'Generando datos...' : 'Este sistema aún no tiene lecturas.'}
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
                  formatter={(value, name, props) => [
                    `${value} W (${props.payload.porcentaje}%)`,
                    'Generación',
                  ]}
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

        <div className="bg-slate-800 p-5 rounded-2xl">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-white font-semibold">🔋 Batería</h2>
            {bateria && !mostrarFormBateria && (
              <div className="flex gap-3">
                <button
                  onClick={handleEditarBateria}
                  className="text-xs text-yellow-500 hover:underline"
                >
                  Editar
                </button>
                <button
                  onClick={handleEliminarBateria}
                  className="text-xs text-red-400 hover:underline"
                >
                  Eliminar
                </button>
              </div>
            )}
          </div>

          {errorBateria && <p className="text-red-400 text-sm mb-3">{errorBateria}</p>}

          {cargandoBateria ? (
            <p className="text-slate-400 text-sm">Cargando batería...</p>
          ) : mostrarFormBateria ? (
            <form onSubmit={handleGuardarBateria} className="space-y-3">
              <input
                type="number"
                step="0.1"
                placeholder="Capacidad (kWh)"
                value={capacidadKwh}
                onChange={(e) => setCapacidadKwh(e.target.value)}
                required
                className="w-full px-4 py-2 rounded-lg bg-slate-700 text-white placeholder-slate-400 outline-none focus:ring-2 focus:ring-yellow-500"
              />
              <input
                type="date"
                value={fechaInstalacionBateria}
                onChange={(e) => setFechaInstalacionBateria(e.target.value)}
                required
                className="w-full px-4 py-2 rounded-lg bg-slate-700 text-white outline-none focus:ring-2 focus:ring-yellow-500"
              />
              <div className="flex gap-2">
                <button
                  type="submit"
                  className="flex-1 py-2 rounded-lg bg-yellow-500 text-slate-900 font-semibold hover:bg-yellow-400 transition"
                >
                  Guardar
                </button>
                <button
                  type="button"
                  onClick={() => setMostrarFormBateria(false)}
                  className="px-4 py-2 rounded-lg bg-slate-700 text-white hover:bg-slate-600 transition"
                >
                  Cancelar
                </button>
              </div>
            </form>
          ) : bateria ? (
            <div className="flex justify-between items-center">
              <div>
                <p className="text-slate-400 text-sm">
                  Instalada: {new Date(bateria.fechaInstalacion).toLocaleDateString()}
                </p>
                <p className="text-slate-500 text-xs mt-1">
                  Capacidad nominal: {bateria.capacidadKwh} kWh
                </p>
              </div>
              <div className="text-right">
                <p className="text-yellow-500 font-bold text-lg">
                  {bateria.capacidadActualKwh} kWh
                </p>
                <p className="text-slate-500 text-xs">
                  {Math.round(bateria.factorDegradacion * 100)}% de su capacidad original
                </p>
              </div>
            </div>
          ) : (
            <div>
              <p className="text-slate-400 text-sm mb-3">
                Este sistema aún no tiene batería registrada.
              </p>
              <button
                onClick={() => setMostrarFormBateria(true)}
                className="px-4 py-2 rounded-lg bg-yellow-500 text-slate-900 font-semibold hover:bg-yellow-400 transition text-sm"
              >
                + Agregar batería
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default SistemaDetalle;