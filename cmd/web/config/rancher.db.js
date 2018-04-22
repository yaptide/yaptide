
function randomPassword(length) {
  var chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOP1234567890";
  var pass = "";
  for (var x = 0; x < length; x++) {
    var i = Math.floor(Math.random() * chars.length);
    pass += chars.charAt(i);
  }
  return pass;
}

var rootPassword = randomPassword(20);
db.updateUser(
  "admin",
  { pwd: rootPassword }
);

var dbs_conf = [
  { user: "yaptide_staging", db: "yaptide_staging", role: "readWrite" },
  { user: "yaptide_staging_owner", db: "yaptide_staging", role: "dbOwner" },
  { user: "yaptide_master", db: "yaptide_master", role: "readWrite" },
  { user: "yaptide_master_owner", db: "yaptide_master", role: "dbOwner" },
  { user: "yaptide_develop", db: "yaptide_develop", role: "readWrite" },
  { user: "yaptide_develop_owner", db: "yaptide_develop", role: "dbOwner" }
];

dbs_conf.forEach(function (item) {
  item.password = randomPassword(10);
});

dbs_conf.forEach(function (item) {
  db.getSiblingDB(item.user).createUser({
    user: item.user,
    pwd: item.password,
    roles: [ { role: item.role, db: item.db }]
  });
});

dbs_conf.forEach(function (item) {
  print(`mongodb://${item.user}:${item.password}@yapt-ide.nazwa.pl:27017/${item.db}`);
});
print(`admin password: ${rootPassword}`);
