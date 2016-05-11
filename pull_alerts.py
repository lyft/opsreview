from datetime import datetime, timedelta
from dateutil import tz
import dateutil.parser

import pygerduty

import settings


pagerduty_service = pygerduty.PagerDuty(
        settings.PAGERDUTY_SUBDOMAIN, settings.PAGERDUTY_API_TOKEN)
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


def recent_incidents_for_service(service_id, time_window_seconds):
    since_time = datetime.now() - timedelta(seconds=time_window_seconds)
    recent_incidents = list(pagerduty_service.incidents.list(service=service_id, since=since_time))
    return recent_incidents


def print_all_incidents():
    escalation_policy = pagerduty_service.escalation_policies.show(settings.ESCALATION_POLICY)
    services = escalation_policy.services

    all_incidents = []

    for service in services:
        service_id = service.id
        service_name = service.name
        incidents = recent_incidents_for_service(service_id, settings.TIME_WINDOW_SECONDS)

        for incident in incidents:
            formatted_incident = FormattedIncident()
            formatted_incident.service = incident.service.name
            formatted_incident.url = incident.html_url
            if hasattr(incident.trigger_summary_data, 'subject'):
                formatted_incident.description = incident.trigger_summary_data.subject
            elif hasattr(incident.trigger_summary_data, 'description'):
                formatted_incident.description = incident.trigger_summary_data.description
            formatted_incident.created_on = dateutil.parser.parse(incident.created_on).astimezone(LOCAL_TZ)

            notes = list(incident.notes.list())
            formatted_notes = []
            for note in notes:
                formatted_notes.append(u'{}: {}'.format(note.user.email, note.content))
            formatted_incident.notes = formatted_notes
            all_incidents.append(formatted_incident)

    all_incidents = sorted(all_incidents, key=(lambda incident: incident.created_on))
    for incident in all_incidents:
        print incident.pretty_output()


if __name__ == '__main__':
    print_all_incidents()
