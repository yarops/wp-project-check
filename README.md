# wp-project-review

Скилл для AI-агентов, который делает техническое ревью WordPress-проекта: плагина, темы или сайта. Охват — изменения ветки, отдельная фича или весь проект. Проверки идут в трёх областях:

- `tooling` — линтеры, статанализ, зависимости, тесты проекта;
- `security` — точки входа, права, nonce, потоки данных;
- `reliability` — контракты API, обработка ошибок, состояние на стыках компонентов.

Результат — отчёт в Markdown и его HTML-копия. Код проекта скилл не меняет.

Все мы видели чеклисты, от которых ревьюеры плачут, а AI-агенты жгут токены, выдавая тонны шума за реальные дефекты. Здесь каждый дефект нужно доказать: показать достижимый путь выполнения и нарушенный контракт языка, WordPress или API. Гипотезы идут отдельно — вместе с тем, что проверено и что осталось за рамками ревью. Подробнее о подходе — в [описании проекта](docs/project-description.md), пример отчёта — в [docs/examples/demo-arcade](docs/examples/demo-arcade/).

## Установка

Нужно:

- агент с поддержкой Agent Skills, например Claude Code;
- Python ≥ 3.8 для HTML-копии отчёта (только стандартная библиотека): `python3`, `python` или `py -3`.

Инструменты проверяемого проекта (`phpcs`, `phpstan`, `composer`, `pnpm` и т. п.) используются, если они в нём установлены.

Установка для Claude Code: для всех проектов — в домашний каталог, для одного проекта — в его корень.

<details open>
<summary><b>Linux, macOS, WSL</b></summary>

```bash
# Для всех проектов:
git clone https://github.com/yarops/wp-project-check.git ~/.claude/skills/wp-project-review

# Для одного проекта (из его корня):
git clone https://github.com/yarops/wp-project-check.git .claude/skills/wp-project-review
```

</details>

<details>
<summary><b>Windows (PowerShell)</b></summary>

```powershell
# Для всех проектов:
git clone https://github.com/yarops/wp-project-check.git "$HOME\.claude\skills\wp-project-review"

# Для одного проекта (из его корня):
git clone https://github.com/yarops/wp-project-check.git ".claude\skills\wp-project-review"
```

</details>

Для других агентов замените `.claude` на их каталог скиллов, например для Codex — `.agents`. Каталог должен называться `wp-project-review`. Обновление — `git pull` в этом каталоге.

## Использование

В сессии агента, в корне проверяемого проекта:

```text
# Codex
$wp-project-review scope: global, areas: tooling, security, reliability

# Claude Code
/wp-project-review scope: global, areas: tooling, security, reliability
```

или обычным языком:

```text
Проверь весь плагин перед релизом
Посмотри права в REST-маршрутах темы
```

Без параметров проверяется весь проект во всех трёх областях. Отчёт сохраняется в проверяемом проекте:

- `docs/reviews/wp-project-review-<дата>-<время>.md`;
- рядом — `.html` с тем же именем.

### Windows

Claude Code на Windows выполняет команды через Git Bash, поэтому скилл работает так же, как в Linux. В агентах с PowerShell поиск, инвентаризация и сборка HTML работают, но проектные скрипты с Unix-синтаксисом (например, npm-скрипты с `rm -rf`) могут быть недоступны — это попадёт в ограничения отчёта. Зависимости проекта, установленные в WSL, из нативной Windows не используются, и наоборот. Поддержка Windows пока не подтверждена прогоном на реальной системе.

## Документация

- [Описание проекта](docs/project-description.md)
- Пользователям: [запуск и параметры](docs/userguides/usage.md), [как читать отчёт](docs/userguides/report.md), [пример](docs/examples/demo-arcade/)
- Разработчикам: [контракт скилла](docs/development/contract.md), [как вносить изменения](docs/development/contributing.md), [планы](docs/development/roadmap/)
