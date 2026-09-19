# Production model integration

## Runtime flow

`frontend/src/SistemaDetalle.jsx` requests `POST /api/sistemas/:id/prediccion` with an ISO timestamp.
The Express API authenticates the user, loads the owned `Sistema` row through Prisma, validates the
persisted geometry, and invokes `predict_pv_power_cli.py` in the data-science virtual environment.
The CLI calls `predict_pv_power(...)`, which obtains Open-Meteo weather, computes pvlib solar position
and POA, loads `models/production_model.joblib`, applies `daylight_model_night_zero`, and returns the
normalized, W, kW, and timestamp fields.

## Persisted system configuration

`Sistema` stores capacity, latitude, longitude, `azimuth_deg`, `tilt_deg`, and `tracking_type`.
The geometry fields are nullable only for records created before this integration. New systems require
all values. Azimuth is degrees clockwise from north; tilt is 0-90 degrees; tracking is `fixed` or
`single_axis`. A tilt of `0` is valid and is never treated as missing.

## Model-owned inputs

Users do not enter GHI, DNI, DHI, POA, temperature, solar position, efficiency, losses, or inverter
parameters. Weather and derived solar features remain backend/model responsibilities. The current
artifact does not use panel efficiency, DC/AC ratio, degradation, shading, losses, configurable albedo,
or configurable GCR as persisted prediction inputs.

## Legacy simulator

`/api/sistemas/:id/simular-dia` remains available as a separate historical UI tool. It is not used by
the production prediction endpoint and must not be interpreted as a model inference result.

## Database migration and environment

The reproducible migration is
`backend/prisma/migrations/20260919090000_agrega_geometria_modelo/migration.sql`.
It adds nullable legacy-safe columns and database check constraints. Apply it with
`npx prisma migrate deploy` from `backend` only after the database URL has been validated.
Never use `prisma migrate reset` against the configured Supabase database.

Prisma migrations use `DIRECT_URL` from `backend/prisma.config.ts`. The Express runtime uses
`DATABASE_URL` in `backend/src/index.js`. Both must target the same Supabase project/database;
the runtime URL may use the pooler while `DIRECT_URL` should use the direct database connection
required for migrations, according to the Supabase connection details.

The runtime and Prisma CLI normalize an unescaped `#` in the credential component before opening
the connection. Do not paste secrets into source control or logs. The preferred long-term form is
to store the exact Supabase-provided URLs with reserved credential characters URL-encoded, for example:

`postgresql://USER:PASSWORD_ENCODED@HOST:PORT/DATABASE?sslmode=require`

Development should use a local or explicitly selected Supabase development database and run
`prisma migrate deploy` after validation. Production should use its own secret manager/environment,
run the same migration once during deployment, and keep `DATABASE_URL` and `DIRECT_URL` out of the
frontend bundle.

## Day simulation

`POST /api/sistemas/:id/simular-dia` now accepts `{ "date": "YYYY-MM-DD" }` and returns one batch
response with 96 fifteen-minute points. The Python batch path uses the same Open-Meteo, pvlib,
tracking, feature contract, model artifact, and daylight strategy as puntual inference. The backend
then applies the existing 0.6% annual panel degradation as post-processing and persists the resulting
points with `origin = "simulado"`. The old climate-factor curve is no longer used by this workflow.

The response contains `date`, resolved `timezone`, `interval_minutes`, `factorDegradacion`, `points`
and persisted `lecturas`. The visual application renders `points`; `/api/sistemas/:id/prediccion`
remains available for punctual inference but has no separate card in the simulation screen.

Day simulations accept `weather` values `clear`, `partial_clouds`, `cloudy`, and `rain`. The scenario
is applied in Python to GHI/DNI/DHI before `pvlib` calculates POA; solar position, geometry, tracking,
temperature, and the trained model remain unchanged. GHI is recomputed as the maximum of scaled GHI
and the physically reconstructed direct-plus-diffuse contribution, while negative radiation is removed
before POA calculation. The UI sends only the scenario identifier and never applies a production
percentage itself.