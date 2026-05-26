function updateUser(user) {
  user.count = user.count + 1;
  user["seen"] = true;
  return user.count;
}
updateUser({ count: 2 });
