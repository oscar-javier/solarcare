// Ejecutar con: node prisma/seed-ciudades.js
// Ciudades principales (usualmente la cabecera departamental) de los 18 departamentos de Honduras

const { PrismaClient } = require('@prisma/client');
const { PrismaPg } = require('@prisma/adapter-pg');
const AdmZip = require('adm-zip');
require('dotenv').config();

const adapter = new PrismaPg({ connectionString: process.env.DATABASE_URL });
const prisma = new PrismaClient({ adapter });

const CIUDADES = [
  { nombre: 'Tegucigalpa', departamento: 'Francisco Morazán', latitud: 14.0723, longitud: -87.1921 },
  { nombre: 'San Pedro Sula', departamento: 'Cortés', latitud: 15.5000, longitud: -88.0333 },
  { nombre: 'Villanueva', departamento: 'Cortés', latitud: 15.3167, longitud: -87.9667 },
  { nombre: 'La Ceiba', departamento: 'Atlántida', latitud: 15.7597, longitud: -86.7822 },
  { nombre: 'Choluteca', departamento: 'Choluteca', latitud: 13.3011, longitud: -87.1897 },
  { nombre: 'Comayagua', departamento: 'Comayagua', latitud: 14.4522, longitud: -87.6375 },
  { nombre: 'Puerto Cortés', departamento: 'Cortés', latitud: 15.8000, longitud: -87.9333 },
  { nombre: 'Danlí', departamento: 'El Paraíso', latitud: 14.0333, longitud: -86.5833 },
  { nombre: 'Juticalpa', departamento: 'Olancho', latitud: 14.6667, longitud: -86.2167 },
  { nombre: 'Santa Rosa de Copán', departamento: 'Copán', latitud: 14.7667, longitud: -88.7833 },
  { nombre: 'Siguatepeque', departamento: 'Comayagua', latitud: 14.6000, longitud: -87.8333 },
  { nombre: 'Tela', departamento: 'Atlántida', latitud: 15.7833, longitud: -87.4667 },
  { nombre: 'Tocoa', departamento: 'Colón', latitud: 15.6833, longitud: -86.0000 },
  { nombre: 'La Esperanza', departamento: 'Intibucá', latitud: 14.3167, longitud: -88.1667 },
  { nombre: 'Nacaome', departamento: 'Valle', latitud: 13.5333, longitud: -87.4833 },
  { nombre: 'Yoro', departamento: 'Yoro', latitud: 15.1333, longitud: -87.1333 },
  { nombre: 'Gracias', departamento: 'Lempira', latitud: 14.5833, longitud: -88.5833 },
  { nombre: 'Roatán', departamento: 'Islas de la Bahía', latitud: 16.3167, longitud: -86.5333 },
  { nombre: 'Ocotepeque', departamento: 'Ocotepeque', latitud: 14.4333, longitud: -89.1833 },
  { nombre: 'Trujillo', departamento: 'Colón', latitud: 15.9167, longitud: -85.9500 },
  { nombre: 'Santa Bárbara', departamento: 'Santa Bárbara', latitud: 14.9194, longitud: -88.2361 },
  { nombre: 'La Paz', departamento: 'La Paz', latitud: 14.3167, longitud: -87.6833 },
  { nombre: 'Puerto Lempira', departamento: 'Gracias a Dios', latitud: 15.2667, longitud: -83.7667 },
];

const DEPARTAMENTOS = [
  'Atlántida', 'Choluteca', 'Colón', 'Comayagua', 'Copán', 'Cortés',
  'El Paraíso', 'Francisco Morazán', 'Gracias a Dios', 'Intibucá', 'Islas de la Bahía',
  'La Paz', 'Lempira', 'Ocotepeque', 'Olancho', 'Santa Bárbara', 'Valle', 'Yoro',
];

const CODIGOS_DEPARTAMENTO = {
  '01': 'Atlántida', '02': 'Choluteca', '03': 'Colón', '04': 'Comayagua',
  '05': 'Copán', '06': 'Cortés', '07': 'El Paraíso', '08': 'Francisco Morazán',
  '09': 'Gracias a Dios', '10': 'Intibucá', '11': 'Islas de la Bahía',
  '12': 'La Paz', '13': 'Lempira', '14': 'Ocotepeque', '15': 'Olancho',
  '16': 'Santa Bárbara', '17': 'Valle', '18': 'Yoro',
};

async function obtenerLocalidadesGeoNames() {
  const respuesta = await fetch('https://download.geonames.org/export/dump/HN.zip');
  if (!respuesta.ok) {
    throw new Error(`GeoNames respondió ${respuesta.status}`);
  }

  const zip = new AdmZip(Buffer.from(await respuesta.arrayBuffer()));
  const archivo = zip.getEntry('HN.txt');
  if (!archivo) throw new Error('El archivo HN.txt no existe en el dump de GeoNames');

  return archivo
    .getData()
    .toString('utf8')
    .split('\n')
    .map((linea) => linea.split('\t'))
    .filter((campos) => campos[6] === 'P' && CODIGOS_DEPARTAMENTO[campos[10]])
    .map((campos) => ({
      nombre: campos[1],
      departamento: CODIGOS_DEPARTAMENTO[campos[10]],
      latitud: Number(campos[4]),
      longitud: Number(campos[5]),
    }))
    .filter((localidad) => Number.isFinite(localidad.latitud) && Number.isFinite(localidad.longitud));
}

async function main() {
  console.log('Poblando ciudades de Honduras...');
  const localidades = await obtenerLocalidadesGeoNames();
  const ciudades = [...CIUDADES, ...localidades];
  const unicas = [...new Map(
    ciudades.map((ciudad) => [`${ciudad.nombre}|${ciudad.departamento}`, ciudad])
  ).values()];
  const existentes = await prisma.ciudadHonduras.findMany({
    select: { nombre: true, departamento: true },
  });
  const clavesExistentes = new Set(
    existentes.map((ciudad) => `${ciudad.nombre}|${ciudad.departamento}`)
  );
  const nuevas = unicas.filter(
    (ciudad) => !clavesExistentes.has(`${ciudad.nombre}|${ciudad.departamento}`)
  );

  for (let inicio = 0; inicio < nuevas.length; inicio += 500) {
    await prisma.ciudadHonduras.createMany({
      data: nuevas.slice(inicio, inicio + 500),
    });
  }
  console.log(`Catálogo obtenido: ${unicas.length} localidades.`);
  console.log(`Nuevas localidades insertadas: ${nuevas.length}.`);
}

main()
  .catch((e) => console.error(e))
  .finally(() => prisma.$disconnect());