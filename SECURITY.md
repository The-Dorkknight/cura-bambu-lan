# Security policy

## Reporting a problem

Please report security problems **privately**: on GitHub open the repository's **Security** tab and choose **Report a vulnerability**. Don't open a public issue for them, and never include your printer's access code.

Include what you found, how to reproduce it, and the plugin, Cura and printer firmware versions. I'll reply as soon as I can; this is a spare-time project, so there is no guaranteed response time.

## Scope

In scope: anything in this repository, for example the plugin trusting data from the printer, leaking the access code, accepting a device that isn't a genuine Bambu printer, or opening network listeners it shouldn't.

Out of scope: the printer's firmware, Bambu Lab's cloud, and Cura itself. Report those to their owners.

See [HOW_IT_WORKS.md](HOW_IT_WORKS.md#security-design) for the design this policy protects.

## Supported versions

Only the latest release gets fixes.
