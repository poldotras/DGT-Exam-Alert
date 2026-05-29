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
