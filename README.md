<div align="center">
  <img src="logo.png" alt="logo" width="200" height="auto" />
  <h1>DGT Exam Alert</h1>
  
  <p>
    A bot that periodically checks the DGT website for driving-exam results and notifies via Telegram, with a web panel to manage who and what is being watched.
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

The system has two parts that share a MySQL database:

- **Bot** (`app/main.py`): periodically queries the DGT website for every exam still under review. When a result appears it notifies via Telegram (screenshot + text), records the full prueba history, infers implied passes, and cancels a carnet's remaining exams once its pipeline is complete. Each exam carries a status so finished ones aren't re-checked.
- **Web panel** (`app/web`, Flask): the single way to manage data — add people, add the carnets/dates to watch, see what's under review, cancel reviews, and consult each person's prueba history and obtained carnets.

> Personas and exams are managed **entirely through the panel**. There is no `personas.json` anymore.

## Web panel

Runs as its own container (`panel`) on `PANEL_PORT` (default `8000`), protected by HTTP Basic Auth (`PANEL_USER` / `PANEL_PASSWORD`). If `PANEL_PASSWORD` is left empty it starts **without** authentication (a warning is logged).

- **Home** — the people list and every exam under review (pending/reviewing) on a single page, with a **Cancel** button per review.
- **Person detail** — obtained carnets, the carnets being reviewed (with their status), the full prueba history, and a form to add a carnet to watch.
- **Add a carnet to review** — choose the carnet and either a single date or a **start–end range** (creates one exam per day); already-registered dates are skipped.

### `carnet` codes

When adding a carnet in the panel, use one of the DGT "clase de permiso" codes below (write `EB`, not `B+E`, and `B`, not `b`):

| Código | Significado | ¿Pipeline? |
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

"¿Pipeline?" indica si ese carnet tiene definida la secuencia de pruebas que dispara la cancelación automática al completarse. Los marcados con `—` son **igualmente válidos**: el bot los consulta, registra resultados y notifica, pero no cancela exámenes automáticamente (no tienen pipeline modelada).

> No escribes la prueba (teórico/práctico/…): el bot lee el historial completo desde la página de resultados de la DGT y registra cada resultado automáticamente.

## Quick start

1. Clone the project

```bash
  git clone https://github.com/poldotras/DGT-Exam-Alert.git
```

2. Create .env

```bash
  cp .env.example .env
```

3. Edit `.env`: Telegram token & chat id, MySQL password, and the panel credentials (`PANEL_USER` / `PANEL_PASSWORD`).

4. Build && start the containers (bot + MySQL + panel)

```bash
  docker compose up -d --build
```

5. Open the panel at `http://localhost:8000` (or your `PANEL_PORT`) and start adding people and the carnets to watch.

## License

Distributed under the no License. See LICENSE.txt for more information.
