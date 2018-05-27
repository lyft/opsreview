from __future__ import absolute_import
from __future__ import division, print_function, unicode_literals
import argparse
import logging
from datetime import datetime
from dateutil import tz
import dateutil.parser

import pygerduty.v2

import settings


logger = logging.getLogger(__name__)

pagerduty_service = pygerduty.v2.PagerDuty(settings.PAGERDUTY_API_TOKEN)
LOCAL_TZ = tz.tzlocal()


class FormattedIncident(object):
    def pretty_output(self):
        return u'Time: {}\nService: {}\nDescription: {}\nURL: {}\nNotes:\n{}\n'.format(
            self.created_on.strftime('%A, %B %-d - %-I:%M %p'),
            self.service,
            self.description,
            self.url,
            self.notes,
        )


def recent_incidents_for_services(services, time_window):
    since_time = datetime.now() - time_window
    service_ids = [service.id for service in services]
    recent_incidents = list(pagerduty_service.incidents.list(service_ids=service_ids, since=since_time, limit=100))
    return recent_incidents


def print_all_incidents(group_by_description=False, include_stats=False, include_incidents_as_blockquote=False):
    services = []
    for escalation_policy in settings.ESCALATION_POLICIES:
        services.extend(list(pagerduty_service.escalation_policies.show(escalation_policy).services))

    all_incidents = []
    incidents = recent_incidents_for_services(services, settings.TIME_WINDOW)

    for incident in incidents:
        formatted_incident = FormattedIncident()
        formatted_incident.service = incident.service.summary
        formatted_incident.url = incident.html_url
        if hasattr(incident, 'title'):
            formatted_incident.description = incident.title
        elif hasattr(incident, 'summary'):
            formatted_incident.description = incident.summary
        elif hasattr(incident, 'id'):
            formatted_incident.description = incident.id
        else:
            logger.warning('action=get_description status=not_found incident={}'.format(incident))
        formatted_incident.created_on = dateutil.parser.parse(incident.created_at).astimezone(LOCAL_TZ)

        notes = list(incident.notes.list())
        formatted_notes = []
        for note in notes:
            formatted_notes.append(u'{}: {}'.format(note.user.summary, note.content))
        formatted_incident.notes = formatted_notes
        all_incidents.append(formatted_incident)

    all_incidents = sort_incidents(all_incidents, group_by_description)
    print_stats(all_incidents, include_stats)
    prev_description = None
    if include_incidents_as_blockquote:
        print("""# Raw incident log
```
""")
    for incident in all_incidents:
        if group_by_description and incident.description != prev_description:
            prev_description = incident.description
            print("########### {} ##########\n".format(incident.description))
        print(incident.pretty_output())
    if include_incidents_as_blockquote:
        print("```")


def print_stats(all_incidents, include_stats):
    if not include_stats:
        return
    actionable = 0
    non_actionable = 0
    not_tagged = 0
    for i in all_incidents:
        if is_actionable(i):
            actionable += 1
        elif is_non_actionable(i):
            non_actionable += 1
        else:
            not_tagged += 1
    print("""# Statistics
| Incidents            | Number |
| -------------------- | ------ |
| Total                | {} |
| Actionable (#a)      | {} |
| Non Actionable (#na) | {} |
| Not Tagged           | {} |
""".format(len(all_incidents), actionable, non_actionable, not_tagged))


def sort_incidents(all_incidents, group_by_description):
    if group_by_description:
        incidents_by_description = {}
        for incident in all_incidents:
            try:
                incidents_by_description[incident.description].append(incident)
            except KeyError:
                incidents_by_description[incident.description] = [incident]
        all_incidents = []
        for description in sorted(incidents_by_description,
                                  key=lambda description: len(incidents_by_description[description]),
                                  reverse=True):
            all_incidents.extend(incidents_by_description[description])
    else:
        all_incidents = sorted(all_incidents, key=lambda i: i.created_on)
    return all_incidents


def is_actionable(incident):
    return bool([note for note in incident.notes if '#a' in note])


def is_non_actionable(incident):
    return bool([note for note in incident.notes if '#na' in note])


if __name__ == '__main__':
    logging.basicConfig()
    parser = argparse.ArgumentParser()
    parser.add_argument("--group-by-description",
                        action="store_true",
                        default=False,
                        help="Group PD incidents by description")
    parser.add_argument("--include-stats",
                        action="store_true",
                        default=False,
                        help="Include incidents stats")
    parser.add_argument("--include-incidents-as-blockquote",
                        action="store_true",
                        default=False,
                        help="Include raw incident log as markdown blockquote")
    args = parser.parse_args()
    print_all_incidents(
        group_by_description=args.group_by_description,
        include_stats=args.include_stats,
        include_incidents_as_blockquote=args.include_incidents_as_blockquote
    )
