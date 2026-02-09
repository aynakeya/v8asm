function greet(user) {
  const name = user.name;
  return `hi, ${name.toUpperCase()}`;
}
greet({ name: 'alice' });
