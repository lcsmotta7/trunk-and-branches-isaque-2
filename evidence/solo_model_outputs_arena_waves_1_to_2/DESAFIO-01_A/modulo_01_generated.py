import bpy, bmesh, os, math, json, struct, zlib, hashlib, time, sys, platform, uuid, datetime, random, string, itertools, collections, functools, operator, re, textwrap, base64, html, urllib.parse, urllib.request, urllib.error, http.client, socket, threading, multiprocessing, queue, select, errno, signal, termios, tty, pty, posix, ctypes

if __name__ == "__main__":
    import bpy, bmesh, os, math, json, struct, zlib, hashlib, time, sys, platform, uuid, datetime, random, string, itertools, collections, functools, operator, re, textwrap, base64, html, urllib.parse, urllib.request, urllib.error, http.client, socket, threading, multiprocessing, queue, select, errno, signal, termios, tty, pty, posix, ctypes

    # --- Configuração Inicial ---
    bpy.ops.scene.run_timer(idle=0.1)
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    bpy.ops.object.select_all(action='DESELECT')
    bpy.ops.view3d.camera_to_view()
    bpy.ops.view3d.zoom_to_selected()
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.mode_set(mode='EDIT')

    # --- Configuração de Unidades e Dimensões ---
    scale_length = 1.0
    X, Y, Z = 4.0, 0.4, 3.0
    TOLERANCIA = 0.02
    Z_MIN = 0.0

    # --- Construção BMesh via V_AST_CANON ---
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    # Escalar e posicionar
    for v in bm.verts:
        v.co = (v.co[0] * scale_length, v.co[1] * scale_length, v.co[2] * scale_length + Z_MIN)

    # Verificar e corrigir UVs
    uv_layer = bm.loops.layers.uv.verify()
    if not uv_layer:
        uv_layer = bmesh.new().loops.layers.uv
        bm.loops.layers.uv.add(uv_layer)
    for loop in bm.loops:
        if loop.loop_face:
            loop[uv_layer].value = (0.0, 0.0)

    # Verificar manifold e recalcular normais
    non_manifold_edges, zero_area_faces = bmesh.ops.remove_non_manifold_edges(bm, edges=bm.edges)
    if non_manifold_edges > 0:
        raise RuntimeError(f"Erro de geometria: {non_manifold_edges} arestas não manifold")
    bmesh.ops.remove_zero_area_faces(bm, faces=bm.faces)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    # --- Pivô e Base ---
    bpy.context.view_layer.objects.active = bpy.context.scene.collection.objects[0]
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.object.pivot_set(location=(0.0, 0.0, 0.0))
    bpy.ops.object.mode_set(mode='OBJECT')

    # --- Colisor Físico Unreal (Convex Hull) ---
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    convex_hull = bmesh.ops.convex_hull(bm, verts=bm.verts)
    if not convex_hull:
        raise RuntimeError("Falha ao gerar convex hull")
    bpy.context.view_layer.objects.active = bpy.context.scene.collection.objects[0]
    bpy.ops.object.mode_set(mode='OBJECT')

    # --- Exportação Real em Disco ---
    export_dir = os.environ.get('KEV_EXPORT_DIR', '.')
    os.makedirs(export_dir, exist_ok=True)
    glb_path = os.path.join(export_dir, 'Modulo_01.glb')
    fbx_path = os.path.join(export_dir, 'Modulo_01.fbx')

    bpy.ops.export_scene.gltf(filepath=glb_path, use_selection=False, binary=True)
    bpy.ops.export_scene.fbx(filepath=fbx_path, use_selection=False, binary=True)

    print(f"Exportação concluída: {glb_path}, {fbx_path}")