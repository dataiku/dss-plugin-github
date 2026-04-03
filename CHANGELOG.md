# Version 1.1.0 - 2026-04-03
* Search GitHub Pull Requests
    * Add a `closed_before_date` parameter to restrict closed pull requests by closing date.
    * Allow `since_date` and `closed_before_date` to use DSS variables in addition to literal `YYYY-MM-DD` values.
    * Validate resolved date values after variable expansion and improve date-related error messages.
* Reliability
    * Retry transient GitHub search failures for HTTP `502`, `503`, and `504` in addition to rate-limit retries.
    * Keep upstream HTTP status codes visible in retry logs to make runtime failures easier to diagnose.
* Internal cleanup
    * Fix incorrect integer identity comparisons in the updated GitHub search pull request code paths.

# Version 1.0.1 - 2025-05-13
* Fix check of unicity that was not working in case of retry due to rate limit.
* Freeze version of PyGithub due to breaking chances on more recent versions around rate limit.

# Version 1.0.0 - 2024-07-02
* Updates
    * Replace auth mechanism by a Personal access token preset
    * Python 3 support
    * Add a state selector on the issues connector
* New components
    * Add a connector to fetch pull requests on specified repositories
    * Add a connector to search pull issues based on a search query
    * Add a connector to search pull requests based on predefined filters

# Version 0.0.4 - 2018-01-10

* Switch to using a code env

# Version 0.0.3 - ?

# 0.0.2 - 2016-04-07

* Add issue body
* Add option to fetch comments
* Fix "learn more" URL

# Version 0.0.1 - 2015-09-28

Initial release
