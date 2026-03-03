#[macro_export]
macro_rules! collab_commands {
    (@commands $callback:ident [ $($acc:tt)* ]) => {
        $callback!([ $($acc)*
            // Collab commands
            $crate::collab::commands::collab_create_session,
            $crate::collab::commands::collab_join_session,
            $crate::collab::commands::collab_leave_session,
            $crate::collab::commands::collab_broadcast_cursor,
            $crate::collab::commands::collab_sync_document,
            $crate::collab::commands::collab_get_server_status,
            $crate::collab::commands::collab_start_server,
            $crate::collab::commands::start_collab_server,
            $crate::collab::commands::stop_collab_server,
            $crate::collab::commands::collab_init_document,
            $crate::collab::commands::collab_update_selection,
            $crate::collab::commands::collab_create_invite,
        ])
    };
}
