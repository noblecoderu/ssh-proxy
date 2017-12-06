#!/bin/sh

# create hostkeys at runtime (-R), don`t fork (-F), log to stderr (-E)
# allow external access to forwarded ports (-a), disable password logins (-s)
exec /usr/sbin/dropbear -RFEas
