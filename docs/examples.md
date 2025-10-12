Kvetch commands can be applied to a particular job (-j) or all jobs in a view (-v). Within a job, 
the command can be applied to a specific build (-b) or all the builds. Builds are referred to by
number of using some special names: lastCompletedBuild, lastSuccessfulBuild, lastFailedBuild. Currently
when displaying "all", you will just see the ones in Jenkins history. The full history is available in
SQLite, but currently there is no way to specify which ones you want other then based on Jenkins history
or specific build numbers.

[Show the history of a particular job](examples/job_history.md)

[Show status of all builds using a view](examples/view_status.md)

