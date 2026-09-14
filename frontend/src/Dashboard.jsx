import { useState, useEffect } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
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

const HORAS_DEL_DIA = [6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18];

// Curva del día calculada de forma determinista (sin variación aleatoria),
// usada solo para el vistazo rápido de "Ver detalles" con el clima real de hoy.
function calcularCurvaDelDia(sistema, categoriaClima) {
  const factorClima = FACTORES_CLIMA[categoriaClima] ?? FACTORES_CLIMA.clear;

  const TASA_DEGRADACION_ANUAL = 0.006;
  const añosDesdeInstalacion =
    (Date.now() - new Date(sistema.fechaInstalacion).getTime()) /
    (1000 * 60 * 60 * 24 * 365.25);
  const factorDegradacion = Math.max(0, 1 - TASA_DEGRADACION_ANUAL * añosDesdeInstalacion);

  const capacidadWatts = sistema.capacidadInstalada * 1000;

  return HORAS_DEL_DIA.map((hora) => {
    const anguloSolar = Math.PI * ((hora - 6) / 12);
    const factorSolar = Math.max(0, Math.sin(anguloSolar));
    const watts = capacidadWatts * factorSolar * factorClima * factorDegradacion;
    return {
      hora: `${hora}:00`,
      watts: Math.round(watts),
    };
  });
}

// Estado exacto "ahora mismo" (con minutos), usado en el indicador junto a la gráfica
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

function Dashboard({ usuario, onLogout, onIrASimular }) {
  const [sistemas, setSistemas] = useState([]);
  const [cargando, setCargando] = useState(true);
  const [mostrarForm, setMostrarForm] = useState(false);
  const [editandoId, setEditandoId] = useState(null);
  const [error, setError] = useState('');

  const [nombre, setNombre] = useState('');
  const [ubicacion, setUbicacion] = useState('');
  const [capacidadInstalada, setCapacidadInstalada] = useState('');
  const [fechaInstalacion, setFechaInstalacion] = useState('');

  const [detalleAbiertoId, setDetalleAbiertoId] = useState(null);
  const [bateriasPorSistema, setBateriasPorSistema] = useState({});

  const [climaReal, setClimaReal] = useState(null);
  const [cargandoClimaReal, setCargandoClimaReal] = useState(true);

  const [horaActual, setHoraActual] = useState(new Date());

  useEffect(() => {
    const intervalo = setInterval(() => setHoraActual(new Date()), 60000);
    return () => clearInterval(intervalo);
  }, []);

  const cargarClimaReal = async () => {
    setCargandoClimaReal(true);
    try {
      const res = await api.get('/clima-actual');
      setClimaReal(res.data);
    } catch (err) {
      setClimaReal(null);
    } finally {
      setCargandoClimaReal(false);
    }
  };

  useEffect(() => {
    cargarClimaReal();
    const intervalo = setInterval(cargarClimaReal, 10 * 60 * 1000);
    return () => clearInterval(intervalo);
  }, []);

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

  const handleVerDetalles = async (sistema) => {
    if (detalleAbiertoId === sistema.id) {
      setDetalleAbiertoId(null);
      return;
    }
    setDetalleAbiertoId(sistema.id);

    if (!(sistema.id in bateriasPorSistema)) {
      try {
        const res = await api.get(`/sistemas/${sistema.id}/bateria`);
        setBateriasPorSistema((prev) => ({ ...prev, [sistema.id]: res.data }));
      } catch (err) {
        setBateriasPorSistema((prev) => ({ ...prev, [sistema.id]: null }));
      }
    }
  };

  const horaTexto = horaActual.toLocaleTimeString('es-HN', {
    hour: '2-digit',
    minute: '2-digit',
  });

  const horaDecimalActual = horaActual.getHours() + horaActual.getMinutes() / 60;
  const horaEtiquetaActual =
    horaDecimalActual >= 6 && horaDecimalActual <= 18
      ? `${Math.round(horaDecimalActual)}:00`
      : null;

  const etiquetaClimaReal = climaReal
    ? OPCIONES_CLIMA.find((o) => o.valor === climaReal.categoria)?.etiqueta ||
      climaReal.categoria
    : null;

  return (
    <div className="min-h-screen bg-slate-900 p-6">
      <div className="max-w-3xl mx-auto">
        <div className="flex justify-between items-center mb-6">
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

        {cargando ? (
          <p className="text-slate-400">Cargando sistemas...</p>
        ) : sistemas.length === 0 ? (
          <p className="text-slate-400">
            Aún no tienes sistemas registrados. Crea el primero arriba.
          </p>
        ) : (
          <div className="grid gap-4">
            {sistemas.map((sistema) => {
              const detalleAbierto = detalleAbiertoId === sistema.id;
              const bateria = bateriasPorSistema[sistema.id];
              const curvaDelDia =
                detalleAbierto && climaReal
                  ? calcularCurvaDelDia(sistema, climaReal.categoria)
                  : [];

              return (
                <div key={sistema.id} className="bg-slate-800 p-5 rounded-2xl">
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
                          onClick={() => handleVerDetalles(sistema)}
                          className="text-xs text-emerald-400 hover:underline"
                        >
                          {detalleAbierto ? 'Ocultar detalles' : 'Ver detalles'}
                        </button>
                        <button
                          onClick={() => onIrASimular(sistema.id)}
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

                  {detalleAbierto && (
                    <div className="mt-4 pt-4 border-t border-slate-700 space-y-4">
                      {climaReal ? (
                        <div className="bg-slate-900/60 rounded-xl p-3">
                          <div className="flex justify-between items-center mb-1 px-1">
                            <div>
                              <p className="text-slate-400 text-xs">San Pedro Sula</p>
                              <p className="text-white text-sm font-semibold">
                                {etiquetaClimaReal} · {climaReal.temperatura}°C
                              </p>
                            </div>
                            <p className="text-slate-400 text-xs">{horaTexto}</p>
                          </div>

                          <div className="flex justify-end px-1 mb-2">
                            {(() => {
                              const estado = calcularEstadoActual(sistema, climaReal.categoria);
                              return estado.generando ? (
                                <p className="text-yellow-500 text-sm font-semibold">
                                  {estado.porcentaje}% · ~{estado.watts} W ahora mismo
                                </p>
                              ) : (
                                <p className="text-slate-300 text-sm">
                                  🌙 Sin generación (fuera de 6 a.m.–6 p.m.)
                                </p>
                              );
                            })()}
                          </div>

                          <ResponsiveContainer width="100%" height={180}>
                            <LineChart data={curvaDelDia}>
                              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                              <XAxis dataKey="hora" stroke="#94a3b8" fontSize={11} />
                              <YAxis stroke="#94a3b8" fontSize={11} />
                              <Tooltip
                                contentStyle={{
                                  backgroundColor: '#1e293b',
                                  border: '1px solid #334155',
                                  borderRadius: '8px',
                                  color: '#fff',
                                }}
                              />
                              {horaEtiquetaActual && (
                                <ReferenceLine
                                  x={horaEtiquetaActual}
                                  stroke="#38bdf8"
                                  strokeDasharray="4 4"
                                  label={{
                                    value: 'Ahora',
                                    position: 'top',
                                    fill: '#38bdf8',
                                    fontSize: 11,
                                  }}
                                />
                              )}
                              <Line
                                type="monotone"
                                dataKey="watts"
                                stroke="#eab308"
                                strokeWidth={2}
                                dot={false}
                              />
                            </LineChart>
                          </ResponsiveContainer>
                          <p className="text-slate-500 text-xs mt-1">
                            Curva estimada del día con el clima real de hoy
                          </p>
                        </div>
                      ) : (
                        <p className="text-slate-500 text-sm">
                          No se pudo obtener el clima real en este momento.
                        </p>
                      )}

                      <div>
                        <p className="text-white text-sm font-medium mb-1">🔋 Batería</p>
                        {bateria === undefined ? (
                          <p className="text-slate-400 text-xs">Cargando...</p>
                        ) : bateria ? (
                          <p className="text-slate-400 text-xs">
                            {bateria.capacidadActualKwh} kWh actuales de{' '}
                            {bateria.capacidadKwh} kWh nominales (
                            {Math.round(bateria.factorDegradacion * 100)}%)
                          </p>
                        ) : (
                          <p className="text-slate-500 text-xs">
                            Sin batería registrada. Agrégala desde "Simular día".
                          </p>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export default Dashboard;