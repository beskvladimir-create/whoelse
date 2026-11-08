# whoelse-network

The open registry behind [whoelse](https://github.com/beskvladimir-create/whoelse): one JSON file
per person under `people/`, describing what they want to build and with whom. Reading needs no
account. Adding yourself is a pull request, which whoelse opens for you.

Rules enforced by CI on every pull request (see `.github/workflows/check.yml`):

1. The file is `people/<slug-of-your-name>.json` and satisfies the schema (`whoelse.network.Request`).
2. `ids.github` equals the GitHub login that opened the pull request. That is how the network knows
   the file is yours: GitHub already checked who you are.
3. One file per pull request; you may only change your own.

Requests expire after three months; whoelse renews yours when you ask it to.
