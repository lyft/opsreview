from __future__ import absolute_import
from __future__ import division, print_function, unicode_literals
import argparse
import logging
from datetime import datetime, timedelta
from dateutil import tz
import dateutil.parser

import pygerduty

import settings


logger = logging.getLogger(__name__)

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

    @classmethod
    def tsv_headers(self):
        return ['create_date',
                'create_hour_pst',
                'incident_number',
                'service',
                'urgency',
                'url',
                'description',
                'minutes_open',
                'num_snoozes']

    def to_tsv_row(self):
        return '\t'.join([
            self.created_on.strftime('%Y-%m-%d'),
            self.created_on.strftime('%H'),
            str(self.incident_number),
            self.service,
            self.urgency,
            self.url,
            self.description,
            str(self.minutes_open),
            str(self.num_snoozes)])

def count_incidents_for_service(service_id):
    since_time = datetime(2017, 1, 2)
    until_time = since_time + timedelta(days=90)
    return pagerduty_service.incidents.count(service=service_id, since=since_time, until=until_time)


def recent_incidents_for_service(service_id, time_window_seconds):
    since_time = datetime.now() - timedelta(seconds=time_window_seconds)
    until_time = since_time + timedelta(days=21)
    recent_incidents = list(pagerduty_service.incidents.list(service=service_id, since=since_time, until=until_time))
    return recent_incidents


def print_all_incidents(group_by_description=False):
    all_incidents = fetch_all_incidents(group_by_description)
    prev_description = None
    for incident in all_incidents:
        if group_by_description and incident.description != prev_description:
            prev_description = incident.description
            print("########### {} ##########\n".format(incident.description))
        print(incident.pretty_output())

def export_all_incidents_to_tsv(group_by_description=False):
    all_incidents = fetch_all_incidents(group_by_description)
    print('\t'.join(FormattedIncident.tsv_headers()))
    for incident in all_incidents:
        print(incident.to_tsv_row())

def count_all_incidents():
    services = []
    for escalation_policy in _get_escalation_policies():
        services.extend(list(pagerduty_service.escalation_policies.show(escalation_policy).services))

    total = 0
    for service in services:
        num = count_incidents_for_service(service.id)
        print('{}: {}'.format(service, num))
        total += num

    print(total)

def fetch_all_incidents(group_by_description=False):
    services = []
    for escalation_policy in _get_escalation_policies():
        services.extend(list(pagerduty_service.escalation_policies.show(escalation_policy).services))

    all_incidents = []

    for service in services:
        service_id = service.id
        incidents = recent_incidents_for_service(service_id, settings.TIME_WINDOW_SECONDS)

        for incident in incidents:
            formatted_incident = FormattedIncident()
            formatted_incident.service = incident.service.name
            formatted_incident.url = incident.html_url
            if hasattr(incident.trigger_summary_data, 'subject'):
                formatted_incident.description = incident.trigger_summary_data.subject
            elif hasattr(incident.trigger_summary_data, 'description'):
                formatted_incident.description = incident.trigger_summary_data.description
            elif hasattr(incident, 'incident_key'):
                formatted_incident.description = incident.incident_key
            else:
                logger.warning('action=get_description status=not_found incident={}'.format(incident))

            created_on = dateutil.parser.parse(incident.created_on).astimezone(LOCAL_TZ)
            formatted_incident.created_on = created_on

            if incident.status == 'resolved':
                resolved_at = dateutil.parser.parse(incident.last_status_change_on).astimezone(LOCAL_TZ)
                formatted_incident.minutes_open = int(round((resolved_at - created_on).seconds / 60.0))
            else:
                formatted_incident.minutes_open = None

            formatted_incident.num_snoozes = len([x for x in incident.log_entries.list() if x.type == 'snooze'])
            formatted_incident.urgency = incident.urgency
            formatted_incident.incident_number = incident.incident_number

            notes = list(incident.notes.list())
            formatted_notes = []
            for note in notes:
                formatted_notes.append(u'{}: {}'.format(note.user.email, note.content))
            formatted_incident.notes = formatted_notes
            all_incidents.append(formatted_incident)
    return sort_incidents(all_incidents, group_by_description)

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


def _get_escalation_policies():
    try:
        escalation_policies = settings.ESCALATION_POLICIES
    except AttributeError:
        logger.warning('setting=ESCALATION_POLICY status=deprecated use=ESCALATION_POLICIES')
        escalation_policies = [settings.ESCALATION_POLICY]
    return escalation_policies


if __name__ == '__main__':
    logging.basicConfig()
    parser = argparse.ArgumentParser()
    parser.add_argument("--group-by-description",
                        action="store_true",
                        default=False,
                        help="Group PD incidents by description")
    args = parser.parse_args()
    #count_all_incidents()
    export_all_incidents_to_tsv()
    # print_all_incidents(group_by_description=args.group_by_description)

