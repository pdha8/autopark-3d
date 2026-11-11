"""Plateau de prise de vue : caméra, lumières, sol du studio, réglages Cycles."""

import math

import bpy
from mathutils import Matrix, Vector

import config as C
from camera import View
from mats import hex_lin

# direction d'où vient la lumière principale (sud-ouest, assez haute)
KEY_FROM = Vector((-0.62, -0.5, 0.82)).normalized()
SCENE_CENTER = (12.0, -8.0)


def setup_render(scene, night, samples=64, scale=1.5):
    scene.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "OPTIX"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = d.type == "OPTIX"
    cy = scene.cycles
    cy.device = "GPU"
    cy.samples = samples
    cy.use_adaptive_sampling = True
    cy.adaptive_threshold = 0.015
    cy.use_denoising = True
    cy.denoiser = "OPTIX"
    cy.max_bounces = 6
    cy.diffuse_bounces = 3
    cy.glossy_bounces = 3
    cy.transmission_bounces = 4
    cy.transparent_max_bounces = 10
    cy.caustics_reflective = False
    cy.caustics_refractive = False
    cy.blur_glossy = 1.0
    cy.sample_clamp_indirect = 8.0
    cy.use_animated_seed = False  # même grain d'une image à l'autre : pas de scintillement

    r = scene.render
    r.resolution_x = int(round(C.FRAME_W * scale / 2) * 2)
    r.resolution_y = int(round(C.FRAME_H * scale / 2) * 2)
    r.resolution_percentage = 100
    r.fps = C.FPS
    r.film_transparent = not night
    r.use_motion_blur = False
    r.motion_blur_shutter = 0.5
    r.use_persistent_data = True
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGB" if night else "RGBA"
    r.image_settings.color_depth = "16"
    r.image_settings.compression = 20
    r.dither_intensity = 0.0

    vs = scene.view_settings
    vs.view_transform = "Standard"
    vs.look = "None"
    vs.exposure = 0.75 if night else -0.08
    vs.gamma = 1.0
    scene.frame_start = 0
    scene.frame_end = C.FRAMES - 1


def setup_camera(scene, view_name, spec=None):
    v = View(view_name, spec)
    cam_data = bpy.data.cameras.new(f"cam_{view_name}")
    cam_data.lens = v.lens
    cam_data.sensor_width = 36.0
    cam_data.sensor_fit = "HORIZONTAL"
    cam_data.clip_start = 5.0
    cam_data.clip_end = 3000.0
    cam = bpy.data.objects.new(f"cam_{view_name}", cam_data)
    scene.collection.objects.link(cam)
    f, r, u = Vector(v.fwd), Vector(v.right), Vector(v.up)
    m = Matrix((r, u, -f)).transposed().to_4x4()
    m.translation = Vector(v.pos)
    cam.matrix_world = m
    scene.camera = cam
    return cam, v


def _world(scene, color, strength, seen=None):
    world = bpy.data.worlds.new("ciel")
    scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputWorld")
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value = color
    bg.inputs["Strength"].default_value = strength
    if seen is None:
        nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
        return world
    # le ciel éclaire la scène ; la caméra, elle, voit la couleur de fond de la page
    cam_bg = nt.nodes.new("ShaderNodeBackground")
    cam_bg.inputs["Color"].default_value = seen
    cam_bg.inputs["Strength"].default_value = 1.0
    path = nt.nodes.new("ShaderNodeLightPath")
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(path.outputs["Is Camera Ray"], mix.inputs["Fac"])
    nt.links.new(bg.outputs["Background"], mix.inputs[1])
    nt.links.new(cam_bg.outputs["Background"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return world


def _sun(scene, energy, angle_deg, color):
    light = bpy.data.lights.new("soleil", "SUN")
    light.energy = energy
    light.angle = math.radians(angle_deg)
    light.color = color
    ob = bpy.data.objects.new("soleil", light)
    scene.collection.objects.link(ob)
    ob.rotation_euler = (-KEY_FROM).to_track_quat("-Z", "Y").to_euler()
    return ob


def _floor(scene, night):
    bpy.ops.mesh.primitive_plane_add(size=6000, location=(0, 0, -C.BASE_T))
    floor = bpy.context.active_object
    floor.name = "sol_studio"
    mat = bpy.data.materials.new("sol_studio")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    if not night:
        bsdf.inputs["Base Color"].default_value = hex_lin(C.PAGE_DAY)
        bsdf.inputs["Roughness"].default_value = 0.95
        floor.is_shadow_catcher = True
    else:
        bsdf.inputs["Base Color"].default_value = hex_lin("#10172a")
        bsdf.inputs["Roughness"].default_value = 0.42
        if "Specular IOR Level" in bsdf.inputs:
            bsdf.inputs["Specular IOR Level"].default_value = 0.35
        # le sol s'efface au loin : la vidéo se fond dans le fond de la page
        out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
        geom = nt.nodes.new("ShaderNodeNewGeometry")
        dist = nt.nodes.new("ShaderNodeVectorMath")
        dist.operation = "DISTANCE"
        dist.inputs[1].default_value = (SCENE_CENTER[0], SCENE_CENTER[1], -C.BASE_T)
        ramp = nt.nodes.new("ShaderNodeMapRange")
        ramp.interpolation_type = "SMOOTHSTEP"
        ramp.inputs["From Min"].default_value = 62.0
        ramp.inputs["From Max"].default_value = 135.0
        ramp.inputs["To Min"].default_value = 0.0
        ramp.inputs["To Max"].default_value = 1.0
        transp = nt.nodes.new("ShaderNodeBsdfTransparent")
        mix = nt.nodes.new("ShaderNodeMixShader")
        nt.links.new(geom.outputs["Position"], dist.inputs[0])
        nt.links.new(dist.outputs["Value"], ramp.inputs["Value"])
        nt.links.new(ramp.outputs["Result"], mix.inputs["Fac"])
        nt.links.new(bsdf.outputs["BSDF"], mix.inputs[1])
        nt.links.new(transp.outputs["BSDF"], mix.inputs[2])
        nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
    floor.data.materials.append(mat)
    return floor


def setup_light(scene, night):
    if night:
        _world(scene, hex_lin("#1d2f58"), 0.3, seen=hex_lin(C.PAGE_NIGHT))
        _sun(scene, 0.12, 14.0, (0.62, 0.74, 1.0))
    else:
        _world(scene, hex_lin("#e6eefb"), 0.58)
        _sun(scene, 3.4, 6.5, (1.0, 0.955, 0.9))
    _floor(scene, night)
