function readUser(user) {
  const city = user?.profile?.address?.city ?? "unknown";
  const len = user?.tags?.[0]?.length || 0;
  return city + ":" + len;
}
readUser({ profile: { address: { city: "Paris" } }, tags: ["abc"] });
