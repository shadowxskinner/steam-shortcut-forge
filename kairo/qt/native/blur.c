/* A narrow bridge to ext-background-effect-v1 on Qt's Wayland connection. */
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wayland-client.h>
#include "ext-background-effect-v1-client-protocol.h"

struct state {
    struct ext_background_effect_manager_v1 *manager;
    struct wl_compositor *compositor;
    uint32_t capabilities;
};

struct active_effect {
    struct wl_display *display;
    struct wl_surface *surface;
    struct ext_background_effect_surface_v1 *effect;
    struct wl_compositor *compositor;
    struct wl_event_queue *queue;
    struct active_effect *next;
};

static struct active_effect *active_effects;

static void handle_capabilities(
    void *data, struct ext_background_effect_manager_v1 *manager,
    uint32_t capabilities)
{
    struct state *s = data;
    (void) manager;
    s->capabilities = capabilities;
}

static const struct ext_background_effect_manager_v1_listener manager_listener = {
    handle_capabilities
};

static void handle_global(void *data, struct wl_registry *registry,
                          uint32_t name, const char *interface, uint32_t version)
{
    struct state *s = data;
    if (strcmp(interface, ext_background_effect_manager_v1_interface.name) == 0) {
        s->manager = wl_registry_bind(registry, name,
                                      &ext_background_effect_manager_v1_interface,
                                      version < 1 ? version : 1);
        ext_background_effect_manager_v1_add_listener(
            s->manager, &manager_listener, s);
    } else if (strcmp(interface, wl_compositor_interface.name) == 0) {
        s->compositor = wl_registry_bind(registry, name,
                                         &wl_compositor_interface,
                                         version < 1 ? version : 1);
    }
}

static void handle_global_remove(void *data, struct wl_registry *registry,
                                 uint32_t name)
{
    (void) data;
    (void) registry;
    (void) name;
}

static const struct wl_registry_listener registry_listener = {
    handle_global, handle_global_remove
};

/*
 * Qt owns the display's default event queue. Kairo's registry and protocol
 * proxies use a private queue so a synchronous discovery roundtrip never
 * dispatches unrelated Qt/PySide events re-entrantly.
 */
static int read_globals(struct wl_display *display, struct state *state,
                        struct wl_registry **registry_out,
                        struct wl_event_queue **queue_out)
{
    struct wl_event_queue *queue = wl_display_create_queue(display);
    if (!queue) return -3;

    struct wl_registry *registry = wl_display_get_registry(display);
    if (!registry) {
        wl_event_queue_destroy(queue);
        return -3;
    }
    wl_proxy_set_queue((struct wl_proxy *) registry, queue);
    wl_registry_add_listener(registry, &registry_listener, state);

    /* Globals arrive first; capabilities from the newly bound manager second. */
    if (wl_display_roundtrip_queue(display, queue) < 0 ||
        wl_display_roundtrip_queue(display, queue) < 0) {
        if (state->manager)
            ext_background_effect_manager_v1_destroy(state->manager);
        if (state->compositor) wl_compositor_destroy(state->compositor);
        wl_registry_destroy(registry);
        wl_event_queue_destroy(queue);
        return -3;
    }

    *registry_out = registry;
    *queue_out = queue;
    return 0;
}

static void release_globals(struct state *state, struct wl_registry *registry,
                            struct wl_event_queue *queue)
{
    if (state->manager)
        ext_background_effect_manager_v1_destroy(state->manager);
    if (state->compositor) wl_compositor_destroy(state->compositor);
    wl_registry_destroy(registry);
    wl_event_queue_destroy(queue);
}

int kairo_blur_available(void *display_ptr)
{
    struct wl_display *display = display_ptr;
    if (!display) return 0;

    struct state s = { NULL, NULL, 0 };
    struct wl_registry *registry = NULL;
    struct wl_event_queue *queue = NULL;
    if (read_globals(display, &s, &registry, &queue) < 0) return 0;

    int found = s.manager && s.compositor &&
        (s.capabilities & EXT_BACKGROUND_EFFECT_MANAGER_V1_CAPABILITY_BLUR);
    release_globals(&s, registry, queue);
    return found;
}

int kairo_blur_enable(void *display_ptr, void *surface_ptr,
                      int32_t width, int32_t height)
{
    struct wl_display *display = display_ptr;
    struct wl_surface *surface = surface_ptr;
    if (!display || !surface) return -1;
    if (width <= 0 || height <= 0) return -6;

    const char *cls = wl_proxy_get_class((struct wl_proxy *) surface);
    if (!cls || strcmp(cls, "wl_surface") != 0) return -2;

    for (struct active_effect *item = active_effects; item; item = item->next) {
        if (item->surface == surface) return 0;
    }

    struct state s = { NULL, NULL, 0 };
    struct wl_registry *registry = NULL;
    struct wl_event_queue *queue = NULL;
    if (read_globals(display, &s, &registry, &queue) < 0) return -3;
    if (!s.manager || !s.compositor ||
        !(s.capabilities & EXT_BACKGROUND_EFFECT_MANAGER_V1_CAPABILITY_BLUR)) {
        release_globals(&s, registry, queue);
        return -4;
    }

    struct ext_background_effect_surface_v1 *effect =
        ext_background_effect_manager_v1_get_background_effect(s.manager, surface);
    if (!effect) {
        release_globals(&s, registry, queue);
        return -5;
    }

    struct wl_region *region = wl_compositor_create_region(s.compositor);
    if (!region) {
        ext_background_effect_surface_v1_destroy(effect);
        release_globals(&s, registry, queue);
        return -6;
    }

    struct active_effect *item = calloc(1, sizeof(*item));
    if (!item) {
        wl_region_destroy(region);
        ext_background_effect_surface_v1_destroy(effect);
        release_globals(&s, registry, queue);
        return -7;
    }

    wl_region_add(region, 0, 0, width, height);
    ext_background_effect_surface_v1_set_blur_region(effect, region);
    wl_region_destroy(region);
    ext_background_effect_manager_v1_destroy(s.manager);
    s.manager = NULL;
    wl_registry_destroy(registry);

    item->display = display;
    item->surface = surface;
    item->effect = effect;
    item->compositor = s.compositor;
    item->queue = queue;
    item->next = active_effects;
    active_effects = item;

    wl_surface_commit(surface);
    wl_display_flush(display);
    return 0;
}

int kairo_blur_resize(void *display_ptr, void *surface_ptr,
                      int32_t width, int32_t height)
{
    struct wl_display *display = display_ptr;
    struct wl_surface *surface = surface_ptr;
    if (!display || !surface) return -1;
    if (width <= 0 || height <= 0) return -6;

    struct active_effect *item = active_effects;
    while (item && (item->surface != surface || item->display != display))
        item = item->next;
    if (!item) return -5;

    struct wl_region *region = wl_compositor_create_region(item->compositor);
    if (!region) return -6;
    wl_region_add(region, 0, 0, width, height);
    ext_background_effect_surface_v1_set_blur_region(item->effect, region);
    wl_region_destroy(region);
    wl_surface_commit(surface);
    wl_display_flush(display);
    return 0;
}

int kairo_blur_disable(void *display_ptr, void *surface_ptr)
{
    struct wl_display *display = display_ptr;
    struct wl_surface *surface = surface_ptr;
    if (!display || !surface) return -1;

    struct active_effect **link = &active_effects;
    while (*link && ((*link)->surface != surface || (*link)->display != display))
        link = &(*link)->next;
    if (!*link) return 0;

    struct active_effect *item = *link;
    *link = item->next;
    ext_background_effect_surface_v1_destroy(item->effect);
    wl_compositor_destroy(item->compositor);
    wl_surface_commit(surface);
    wl_display_flush(display);
    wl_event_queue_destroy(item->queue);
    free(item);
    return 0;
}
