/** Use the API's calendar date and timezone, not the browser's local timezone. */
export function contextWindows(dateContext: string | null, timezone: string) {
  if (!dateContext) return undefined;
  const formatter = new Intl.DateTimeFormat("en-US", { timeZone: timezone, timeZoneName: "longOffset" });
  function atHour(hour: string) {
    const localTime = `${dateContext}T${hour}:00:00`;
    let instant = new Date(`${localTime}Z`);
    // Recheck the offset at the resolved instant for dates near a DST change.
    for (let pass = 0; pass < 2; pass++) {
      const zoneName = formatter.formatToParts(instant).find((part) => part.type === "timeZoneName")!.value;
      const offset = zoneName.replace("GMT", "") || "+00:00";
      instant = new Date(`${localTime}${offset}`);
    }
    return instant.toISOString();
  }
  // Match the existing API default availability; these are window bounds,
  // not fixed start/end times or deadlines assigned to individual tasks.
  return [{ start: atHour("09"), end: atHour("21") }];
}
