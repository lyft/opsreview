# opsreview
Compile a report of recent PagerDuty alerts for a single escalation policy.

## Purpose
To keep the on-call duty tolerable, it's important to regularly review recent alerts and determine what actions need to be taken. That might be fixing the originating issue, or modifying your alerting behaviors.

Using the opsreview tool, you can quickly compile a report on recent alerts for a single escalation policy and determine what actions should be taken.

## Example Output
```
> python pull_alerts.py

Time: Tuesday, January 19 - 9:19 AM
Service: api
Description: Failing API alarm: CRON failure
URL: https://subdomain.pagerduty.com/incidents/ABC123
Notes:
['bob@lyft.com: #a - Re-ran CRON']

Time: Tuesday, January 19 - 12:03 PM
Service: api
Description: Failing API alarm: CPU percent > 10
URL: https://subdomain.pagerduty.com/incidents/ABC124
Notes:
['bob@lyft.com: #na - Temporary spike in CPU, no action taken. Alert is too sensitive.']

Time: Tuesday, January 19 - 1:35 PM
Service: www
Description: Failing WWW alarm: 5XX percent > 5
URL: https://subdomain.pagerduty.com/incidents/ABC125
Notes:
['sally@lyft.com: #a - Bad deploy']
```

## Setup
Update your settings.

```bash
cp settings_example.py settings.py

# Update settings.py for your PagerDuty escalation policy.
#
# Find the 6 character ESCALATION_POLICY id visiting
#   https://yoursubdomain.pagerduty.com/escalation_policies
# and searching for the escalation policy you want to audit.
# The code will be at the end of the URL.
#
# PAGERDUTY_SUBDOMAIN = 'yoursubdomain'
# PAGERDUTY_API_TOKEN = 'yourapitoken'
# ESCALATION_POLICY = 'PYODVQB'  # Get from https://yoursubdomain.pagerduty.com/escalation_policies#PYODVQB
# TIME_WINDOW_SECONDS = 7 * 24 * 60 * 60  # 1 week
```

Find the 6 character code by going to https://yoursubdomain.pagerduty.com/escalation_policies and searching for the escalation policy whose alerts you want to audit. The code will be at the end of the URL. For example https://yoursubdomain.pagerduty.com/escalation_policies#PYODVQB should use the code `'PYODVQB'`.

Set up your environment.
```bash
virtualenv venv
source venv/bin/activate
pip install -r requirements.txt
```

Run the script.
```bash
python pull_alerts.py
```
