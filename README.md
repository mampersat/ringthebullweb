# Ring the Bull — Score Keeper

![Ring the Bull](images/ring-the-bull-promo.png)

A simple, phone-friendly web app for keeping score while playing **Ring the Bull** — the classic pub/carnival hook-and-ring game.

**Live app:** https://mampersat.com/ringthebull/

## What is Ring the Bull?

Ring the Bull is a traditional pub game: players swing a ring on a rope, trying to hook it onto a bull's horn mounted on the wall. See the [Pineapple Inn, Shaw, Greater Manchester rules](https://www.mastersofgames.com/rules/ringing-bull-rules.htm) for the full traditional rules.

This app uses the casual scoring variant:
- Each player gets 21 shots
- Whoever lands the most hooks (hits) wins

## Features

- Big, thumb-friendly HIT / MISS buttons
- A 21-shot grid showing the whole game at a glance
- Undo for the last shot
- Score persists across page reloads (saved to `localStorage`)
- A big final-score screen with a Share button (native share sheet, or copy-to-clipboard) once the game ends

## Running locally

Just open `index.html` in a browser — no build step, no dependencies.

## Deploying

`./deploy.sh` uploads `index.html` to S3 (`s3://mampersat.com/ringthebull/`).

## Related

Looking for the Android app instead? See [mampersat/RingingTheBull](https://github.com/mampersat/RingingTheBull) (Flutter).
