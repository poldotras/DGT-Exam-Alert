<div align="center">
  <img src="logo.png" alt="logo" width="200" height="auto" />
  <h1>DGT Exam Alert</h1>
  
  <p>
    This repository is a bot that periodically checks for solutions to incomplete exams and notifies users via Telegram when it receives a result.
  </p>
  
<h4>
    <a href="https://github.com/poldotras/DGT-Exam-Alert/issues/">Report Bug</a>
  <span> · </span>
    <a href="https://github.com/poldotras/DGT-Exam-Alert/issues/">Request Feature</a>
  <span> · </span>
    <a href="https://github.com/poldotras/DGT-Exam-Alert/pulls">Contribute</a>
  </h4>
</div>

<br />

## Disclaimer

These modifications were made quickly and easily to adapt to my needs. It was developed based on the DGT website design as of March 2026. It is possible that if the site is modified, the bot may not function correctly.

## About the Project

When the bot starts, it reads the personas.json file and adds the data to the MySQL database if it hasn't already been created. Periodically, the data stored in the database is updated to check for exam results. Exams are managed with statuses to avoid checking exams where results have already been obtained; these statuses are stored in the database. As soon as an exam result is obtained, a notification is sent via Telegram with a screenshot of the website and text.

## personas.json format

Each entry describes one person + licence (`carnet`) and the exam date(s) to check:

```json
[
  {
    "nif": "12345678Z",
    "nombre": "Nombre",
    "carnet": "B",
    "fecha_nacimiento": "18/08/2004",
    "fecha_examen": "02/11/2022"
  }
]
```

- `fecha_examen` accepts a single `"dd/mm/yyyy"`, a list `["dd/mm/yyyy", ...]`, or a range `{"start": "dd/mm/yyyy", "end": "dd/mm/yyyy"}`.
- You do **not** write the prueba (teórico/práctico/…): the bot reads the full prueba history straight from the DGT result page and registers every result automatically.

### `carnet` codes

The `carnet` value must be written **exactly** as one of the DGT "clase de permiso" codes below (there is no normalisation or aliasing — write `EB`, not `B+E`, and `B`, not `b`). Any other value is rejected and that entry is skipped.

| Código (JSON) | Significado | ¿Pipeline? |
|---|---|---|
| `A` | A | ✅ |
| `AM` | AM | ✅ |
| `AML` | AM Limitado | ✅ |
| `A1` | A1 | ✅ |
| `A2` | A2 | ✅ |
| `B` | B | ✅ |
| `EB` | B+E | ✅ |
| `B96` | B96 | — |
| `C` | C | ✅ |
| `EC` | C+E | ✅ |
| `C1` | C1 | ✅ |
| `EC1` | C1+E | ✅ |
| `D` | D | ✅ |
| `ED` | D+E | ✅ |
| `D1` | D1 | ✅ |
| `ED1` | D1+E | ✅ |
| `LCC` | LCC | — |
| `LCM` | LCM | — |
| `LVA` | LVA | — |
| `BC` | M.P. Básico Común | — |
| `CI` | M.P. Cisternas | — |
| `CX1` | M.P. Explosivos | — |
| `C7` | M.P. Radiactivo | — |
| `RPV` | RPV (Pérdida vigencia) | — |

"¿Pipeline?" indica si ese carnet tiene definida la secuencia de pruebas que dispara la cancelación automática al completarse. Los marcados con `—` son **igualmente válidos** en el JSON: el bot los consulta, registra resultados y notifica, pero no cancela exámenes automáticamente (no tienen pipeline modelada).

## Quick start

1. Clone the project

```bash
  git clone https://github.com/poldotras/DGT-Exam-Alert.git
```

2. Create .env

```bash
  cp .env.example .env
```

3. Edit .env with token, chat id ...

4. Build && Start Containers

```bash
  docker compose up -d --build
```

## License

Distributed under the no License. See LICENSE.txt for more information.
