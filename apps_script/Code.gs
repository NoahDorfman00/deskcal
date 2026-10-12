/**
 * Desk Calendar feed: serves your upcoming events as JSON for the Pi to poll.
 * Runs inside your Google account, so no third-party app approval is needed.
 * Setup: see "Calendar feed" in README.md.
 */

const CALENDAR_ID = 'primary';
const DAYS_BACK = 1;
const DAYS_AHEAD = 8;

// Only what the display uses; nothing else leaves your account.
const FIELDS =
  'nextPageToken,items(id,iCalUID,status,eventType,summary,start,end,location,' +
  'description,hangoutLink,conferenceData/conferenceSolution/name,attendees(self,responseStatus))';

function doGet() {
  const now = Date.now();
  const params = {
    timeMin: new Date(now - DAYS_BACK * 864e5).toISOString(),
    timeMax: new Date(now + DAYS_AHEAD * 864e5).toISOString(),
    singleEvents: true, // expand recurring events
    orderBy: 'startTime',
    maxResults: 250,
    fields: FIELDS,
  };
  let items = [];
  do {
    const page = Calendar.Events.list(CALENDAR_ID, params);
    items = items.concat(page.items || []);
    params.pageToken = page.nextPageToken;
  } while (params.pageToken);

  for (const item of items) {
    // The description is only needed to spot video links, so send just its URLs.
    item.description = ((item.description || '').match(/https:\/\/[^\s<>"']+/g) || []).join(' ');
  }
  return ContentService.createTextOutput(JSON.stringify({ items: items }))
    .setMimeType(ContentService.MimeType.JSON);
}
