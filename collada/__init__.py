####################################################################
#                                                                  #
# THIS FILE IS PART OF THE pycollada LIBRARY SOURCE CODE.          #
# USE, DISTRIBUTION AND REPRODUCTION OF THIS LIBRARY SOURCE IS     #
# GOVERNED BY A BSD-STYLE SOURCE LICENSE INCLUDED WITH THIS SOURCE #
# IN 'COPYING'. PLEASE READ THESE TERMS BEFORE DISTRIBUTING.       #
#                                                                  #
# THE pycollada SOURCE CODE IS (C) COPYRIGHT 2011                  #
# by Jeff Terrace and contributors                                 #
#                                                                  #
####################################################################

"""Main module for collada (pycollada) package.

You will find here class `Collada` which is the one to use to access
collada file, and some exceptions that are raised in case the input
file is not what is expected.

"""

from lxml import etree as ElementTree
from lxml.builder import ElementMaker
import zipfile
from StringIO import StringIO
import types
import traceback
from datetime import datetime
import posixpath
import os.path


E = ElementMaker(namespace='http://www.collada.org/2005/11/COLLADASchema',
                 nsmap={None: 'http://www.collada.org/2005/11/COLLADASchema'})
def tag( text ):
    return str(ElementTree.QName( 'http://www.collada.org/2005/11/COLLADASchema', text ))

class DaeObject(object):
    """This class is the abstract interface to all collada objects.

    Every <tag> in a COLLADA that we recognize and load has mirror
    class deriving from this one. All instances will have at least
    a :meth:`load` method which creates the object from an xml node and
    an attribute called :attr:`xmlnode` with the ElementTree representation
    of the data. Even if it was created on the fly. If the object is
    not read-only, it will also have a :meth:`save` method which saves the
    object's information back to the :attr:`xmlnode` attribute.

    """

    xmlnode = None
    """ElementTree representation of the data."""

    @staticmethod
    def load(collada, localscope, node):
        """Load and return a class instance from an XML node.

        Inspect the data inside node, which must match
        this class tag and create an instance out of it.

        :param collada.Collada collada:
          The collada file object where this object lives
        :param dict localscope:
          If there is a local scope where we should look for local ids 
          (sid) this is the dictionary. Otherwise empty dict ({})
        :param node:
          An Element from python's ElementTree API

        """
        raise Exception('Not implemented')

    def save(self):
        """Put all the data to the internal xml node (xmlnode) so it can be serialized."""

class DaeError(Exception):
    """General DAE exception."""
    def __init__(self, msg):
        super(DaeError,self).__init__()
        self.msg = msg

    def __str__(self): return type(self).__name__ + ': ' + self.msg
    def __repr__(self): return type(self).__name__ + '("' + self.msg + '")'

class DaeIncompleteError(DaeError):
    """Raised when needed data for an object isn't there."""
    pass

class DaeBrokenRefError(DaeError):
    """Raised when a referenced object is not found in the scope."""
    pass

class DaeMalformedError(DaeError):
    """Raised when data is found to be corrupted in some way."""
    pass

class DaeUnsupportedError(DaeError):
    """Raised when some unexpectedly unsupported feature is found."""
    pass

class DaeSaveValidationError(DaeError):
    """Raised when XML validation fails when saving."""
    pass

import geometry
import scene
import material
import camera
import light
import controller
import animation
import asset
import schema
from util import IndexedList

class Collada(object):
    """This is the main class used to create and load collada documents"""

    geometries = property( lambda s: s._geometries, lambda s,v: s._setIndexedList('_geometries', v), doc="""
    A list of :class:`collada.geometry.Geometry` objects. Can also be indexed by id""" )
    controllers = property( lambda s: s._controllers, lambda s,v: s._setIndexedList('_controllers', v), doc="""
    A list of :class:`collada.controller.Controller` objects. Can also be indexed by id""" )
    animations = property( lambda s: s._animations, lambda s,v: s._setIndexedList('_animations', v), doc="""
    A list of :class:`collada.animation.Animation` objects. Can also be indexed by id""" )
    lights = property( lambda s: s._lights, lambda s,v: s._setIndexedList('_lights', v), doc="""
    A list of :class:`collada.light.Light` objects. Can also be indexed by id""" )
    cameras = property( lambda s: s._cameras, lambda s,v: s._setIndexedList('_cameras', v), doc="""
    A list of :class:`collada.camera.Camera` objects. Can also be indexed by id""" )
    images = property( lambda s: s._images, lambda s,v: s._setIndexedList('_images', v), doc="""
    A list of :class:`collada.material.CImage` objects. Can also be indexed by id""" )
    effects = property( lambda s: s._effects, lambda s,v: s._setIndexedList('_effects', v), doc="""
    A list of :class:`collada.material.Effect` objects. Can also be indexed by id""" )
    materials = property( lambda s: s._materials, lambda s,v: s._setIndexedList('_materials', v), doc="""
    A list of :class:`collada.material.Effect` objects. Can also be indexed by id""" )
    nodes = property( lambda s: s._nodes, lambda s,v: s._setIndexedList('_nodes', v), doc="""
    A list of :class:`collada.scene.Node` objects. Can also be indexed by id""" )
    scenes = property( lambda s: s._scenes, lambda s,v: s._setIndexedList('_scenes', v), doc="""
    A list of :class:`collada.scene.Scene` objects. Can also be indexed by id""" )

    def __init__(self, filename=None, ignore=None, aux_file_loader=None, zip_filename=None, validate_output=False):
        """Load collada data from filename or file like object.
        
        :param filename:
          String containing path to filename to open or file-like object.
          Uncompressed .dae files are supported, as well as zip file archives.
          If this is set to ``None``, a new collada instance is created.
        :param list ignore:
          A list of :class:`collada.DaeError` types that should be ignored
          when loading the collada document. Instances of these types will
          be added to :attr:`errors` after loading but won't be raised.
          Only used if `filename` is not ``None``.
        :param function aux_file_loader:
          Referenced files (e.g. texture images) are loaded from disk when
          reading from the local filesystem and from the zip archive when
          loading from a zip file. If these files are coming from another source
          (e.g. database) and/or you're loading with StringIO, set this to
          a function that given a filename, returns the binary data in the file.
          If `filename` is ``None``, you must set this parameter if you want to
          load auxiliary files.
        :param str zip_filename:
          If the file being loaded is a zip archive, you can set this parameter
          to indicate the file within the archive that should be loaded. If not
          set, a file that ends with .dae will be searched.
        :param bool validate_output:
          If set to True, the XML written when calling :meth:`save` will be
          validated against the COLLADA 1.4.1 schema. If validation fails, the
          :class:`collada.DaeSaveValidationError` exception will be thrown.
        """
        
        self.errors = []
        """List of :class:`collada.DaeError` objects representing errors encounterd while loading collada file"""
        self.assetInfo = None
        """Instance of :class:`collada.asset.Asset` containing asset information"""
        
        self._geometries = IndexedList([], ('id',))
        self._controllers = IndexedList([], ('id',))
        self._animations = IndexedList([], ('id',))
        self._lights = IndexedList([], ('id',))
        self._cameras = IndexedList([], ('id',))
        self._images = IndexedList([], ('id',))
        self._effects = IndexedList([], ('id',))
        self._materials = IndexedList([], ('id',))
        self._nodes = IndexedList([], ('id',))
        self._scenes = IndexedList([], ('id',))
        
        self.scene = None
        """The default scene. This is either an instance of :class:`collada.scene.Scene` or `None`."""
        
        if validate_output:
            self.validator = schema.ColladaValidator()
        else:
            self.validator = None
            
        self.maskedErrors = []
        if ignore is not None:
            self.ignoreErrors( *ignore )
        
        if filename is None:
            self.filename = None
            self.zfile = None
            self.getFileData = aux_file_loader
            
            self.xmlnode = ElementTree.ElementTree(
                               E.COLLADA(
                                   E.library_cameras(),
                                   E.library_controllers(),
                                   E.library_effects(),
                                   E.library_geometries(),
                                   E.library_images(),
                                   E.library_lights(),
                                   E.library_materials(),
                                   E.library_nodes(),
                                   E.library_visual_scenes(),
                                   E.scene(),
                               version='1.4.1'))
            """ElementTree representation of the collada document"""
            
            self.assetInfo = asset.Asset()
            
            return
            
        
        if type(filename) in [types.StringType, types.UnicodeType]:
            fdata = open(filename, 'rb')
            self.filename = filename
            self.getFileData = self._getFileFromDisk
        else:
            fdata = filename # assume it is a file like object
            self.filename = None
            self.getFileData = self._nullGetFile
        strdata = fdata.read()
        
        try:
            self.zfile = zipfile.ZipFile(StringIO(strdata), 'r')
        except:
            self.zfile = None
        
        if self.zfile:
            self.filename = ''
            daefiles = []
            if zip_filename is not None:
                self.filename = zip_filename
            else:
                for name in self.zfile.namelist():
                    if name.upper().endswith('.DAE'):
                        daefiles.append(name)
                for name in daefiles:
                    if not self.filename:
                        self.filename = name
                    elif "MACOSX" in self.filename:
                        self.filename = name
            if not self.filename or self.filename not in self.zfile.namelist():
                raise DaeIncompleteError('COLLADA file not found inside zip compressed file')
            data = self.zfile.read(self.filename)
            self.getFileData = self._getFileFromZip
        else:
            data = strdata
        
        if aux_file_loader is not None:
            self.getFileData = aux_file_loader
        
        etree_parser = ElementTree.XMLParser(remove_comments=True, remove_blank_text=True)
        try:
            self.xmlnode = ElementTree.ElementTree(element=None, file=StringIO(data), parser=etree_parser)
        except ElementTree.XMLSyntaxError, e:
            raise DaeMalformedError("XML Syntax Parsing Error: %s" % e)
        
        self._loadAssetInfo()
        self._loadImages()
        self._loadEffects()
        self._loadMaterials()
        self._loadAnimations()
        self._loadGeometry()
        self._loadControllers()
        self._loadLights()
        self._loadCameras()
        self._loadNodes()
        self._loadScenes()
        self._loadDefaultScene()

    def _setIndexedList(self, propname, data):
        setattr(self, propname, IndexedList(data, ('id',)))

    def handleError(self, error):
        self.errors.append(error)
        if not type(error) in self.maskedErrors:
            raise

    def ignoreErrors(self, *args):
        """Add exceptions to the mask for ignoring or clear the mask if None given.

        You call c.ignoreErrors(e1, e2, ... ) if you want the loader to ignore those
        exceptions and continue loading whatever it can. If you want to empty the
        mask so all exceptions abort the load just call c.ignoreErrors(None).

        """
        if args == [ None ]:
            self.maskedErrors = []
        else:
            for e in args: self.maskedErrors.append(e)
    
    def _getFileFromZip(self, fname):
        """Return the binary data of an auxiliary file from a zip archive as a string."""
        if not self.zfile:
            raise DaeBrokenRefError('Trying to load an auxiliar file %s but we are not reading from a zip'%fname)
        basepath = posixpath.dirname(self.filename)
        aux_path = posixpath.normpath(posixpath.join(basepath, fname))
        if aux_path not in self.zfile.namelist():
            raise DaeBrokenRefError('Auxiliar file %s not found in archive'%fname)
        return self.zfile.read( aux_path )

    def _getFileFromDisk(self, fname):
        """Return the binary data of an auxiliary file from the local disk relative to the file path loaded."""
        if self.zfile:
            raise DaeBrokenRefError('Trying to load an auxiliar file %s from disk but we are reading from a zip file'%fname)
        basepath = os.path.dirname(self.filename)
        aux_path = os.path.normpath(os.path.join(basepath, fname))
        if not os.path.exists(aux_path):
            raise DaeBrokenRefError('Auxiliar file %s not found on disk'%fname)
        fdata = open(aux_path, 'rb')
        return fdata.read()
    
    def _nullGetFile(self, fname):
        raise DaeBrokenRefError('Trying to load auxiliary file but collada was not loaded from disk, zip, or with custom handler')

    def _loadAssetInfo(self):
        """Load information in <asset> tag"""
        assetnode = self.xmlnode.find( tag('asset') )
        if assetnode is not None:
            self.assetInfo = asset.Asset.load(self, {}, assetnode)
        else:
            self.assetInfo = asset.Asset()
                    
    def _loadGeometry(self):
        """Load geometry library."""
        libnodes = self.xmlnode.findall( tag('library_geometries') )
        if libnodes is not None:
            for libnode in libnodes:
                if libnode is not None:
                    for geomnode in libnode.findall(tag('geometry')):
                        if geomnode.find(tag('mesh')) is None: continue
                        try: G = geometry.Geometry.load( self, {}, geomnode )
                        except DaeError, ex: self.handleError(ex)
                        else:
                            self.geometries.append( G )
    
    def _loadControllers(self):
        """Load controller library."""
        libnodes = self.xmlnode.findall( tag('library_controllers') )
        if libnodes is not None:
            for libnode in libnodes:
                if libnode is not None:
                    for controlnode in libnode.findall(tag('controller')):
                        if controlnode.find(tag('skin')) is None and controlnode.find(tag('morph')) is None:
                            continue
                        try: C = controller.Controller.load( self, {}, controlnode )
                        except DaeError, ex: self.handleError(ex)
                        else:
                            self.controllers.append( C )
    
    def _loadAnimations(self):
        """Load animation library."""
        libnodes = self.xmlnode.findall( tag('library_animations') )
        if libnodes is not None:
            for libnode in libnodes:
                if libnode is not None:
                    for animnode in libnode.findall(tag('animation')):
                        try: A = animation.Animation.load( self, {}, animnode )
                        except DaeError, ex: self.handleError(ex)
                        else:
                            self.animations.append( A )
    
    def _loadLights(self):
        """Load light library."""
        libnodes = self.xmlnode.findall( tag('library_lights') )
        if libnodes is not None:
            for libnode in libnodes:
                if libnode is not None:
                    for lightnode in libnode.findall(tag('light')):
                        try: lig = light.Light.load( self, {}, lightnode )
                        except DaeError, ex: self.handleError(ex)
                        else:
                            self.lights.append( lig )

    def _loadCameras(self):
        """Load camera library."""
        libnodes = self.xmlnode.findall( tag('library_cameras') )
        if libnodes is not None:
            for libnode in libnodes:
                if libnode is not None:
                    for cameranode in libnode.findall(tag('camera')):
                        try: cam = camera.Camera.load( self, {}, cameranode )
                        except DaeError, ex: self.handleError(ex)
                        else:
                            self.cameras.append( cam )

    def _loadImages(self):
        """Load image library."""
        libnodes = self.xmlnode.findall( tag('library_images') )
        if libnodes is not None:
            for libnode in libnodes:
                if libnode is not None:
                    for imgnode in libnode.findall(tag('image')):
                        try: img = material.CImage.load( self, {}, imgnode )
                        except DaeError, ex: self.handleError(ex)
                        else:
                            self.images.append( img )

    def _loadEffects(self):
        """Load effect library."""
        libnodes = self.xmlnode.findall( tag('library_effects') )
        if libnodes is not None:
            for libnode in libnodes:
                if libnode is not None:
                    for effectnode in libnode.findall(tag('effect')):
                        try: effect = material.Effect.load( self, {}, effectnode )
                        except DaeError, ex: self.handleError(ex)
                        else:
                            self.effects.append( effect )

    def _loadMaterials(self):
        """Load material library."""
        libnodes = self.xmlnode.findall( tag('library_materials'))
        if libnodes is not None:
            for libnode in libnodes:
                if libnode is not None:
                    for materialnode in libnode.findall(tag('material')):
                        try: mat = material.Material.load( self, {}, materialnode )
                        except DaeError, ex: self.handleError(ex)
                        else:
                            self.materials.append( mat )

    def _loadNodes(self):
        libnodes = self.xmlnode.findall( tag('library_nodes') )
        if libnodes is not None:
            for libnode in libnodes:
                if libnode is not None:
                    tried_loading = []
                    succeeded = False
                    for node in libnode.findall(tag('node')):
                        try: N = scene.loadNode(self, node, {})
                        except scene.DaeInstanceNotLoadedError, ex:
                            tried_loading.append((node, ex))
                        except DaeError, ex: self.handleError(ex)
                        else:
                            if N is not None:
                                self.nodes.append( N )
                                succeeded = True
                    while len(tried_loading) > 0 and succeeded:
                        succeeded = False
                        next_tried = []
                        for node, ex in tried_loading:
                            try: N = scene.loadNode(self, node, {})
                            except scene.DaeInstanceNotLoadedError, ex:
                                next_tried.append((node, ex))
                            except DaeError, ex: self.handleError(ex)
                            else:
                                if N is not None:
                                    self.nodes.append( N )
                                    succeeded = True
                        tried_loading = next_tried
                    if len(tried_loading) > 0:
                        for node, ex in tried_loading:
                            raise DaeBrokenRefError(ex.msg)

    def _loadScenes(self):
        """Load scene library."""
        libnodes = self.xmlnode.findall( tag('library_visual_scenes') )
        if libnodes is not None:
            for libnode in libnodes:
                if libnode is not None:
                    for scenenode in libnode.findall(tag('visual_scene')):
                        try: S = scene.Scene.load( self, scenenode )
                        except DaeError, ex: self.handleError(ex)
                        else:
                            self.scenes.append( S )

    def _loadDefaultScene(self):
        """Loads the default scene from <scene> tag in the root node."""
        node = self.xmlnode.find('%s/%s'%( tag('scene'), tag('instance_visual_scene') ) )
        try:
            if node != None:
                sceneid = node.get('url')
                if not sceneid.startswith('#'):
                    raise DaeMalformedError('Malformed default scene reference to %s: '%sceneid)
                self.scene = self.scenes.get(sceneid[1:])
                if not self.scene:
                    raise DaeBrokenRefError('Default scene %s not found'%sceneid)
        except DaeError, ex: self.handleError(ex)

    def save(self):
        """Saves the collada document back to :attr:`xmlnode`"""
        libraries = [(self.geometries, 'library_geometries'),
                     (self.controllers, 'library_controllers'),
                     (self.lights, 'library_lights'),
                     (self.cameras, 'library_cameras'),
                     (self.images, 'library_images'),
                     (self.effects, 'library_effects'),
                     (self.materials, 'library_materials'),
                     (self.nodes, 'library_nodes'),
                     (self.scenes, 'library_visual_scenes')]
        
        self.assetInfo.save()
        assetnode = self.xmlnode.getroot().find( tag('asset') )
        if assetnode is not None:
            self.xmlnode.getroot().replace(assetnode, self.assetInfo.xmlnode)
        else:
            self.xmlnode.getroot().insert(0, self.assetInfo.xmlnode)
        
        library_loc = 0
        for i, node in enumerate(self.xmlnode.getroot()):
            if node.tag == tag('asset'):
                library_loc = i+1
        
        for arr, name in libraries:
            node = self.xmlnode.find( tag(name) )
            if node is None:
                if len(arr) == 0:
                    continue
                self.xmlnode.getroot().insert(library_loc, E(name))
                node = self.xmlnode.find( tag(name) )
            elif node is not None and len(arr) == 0:
                self.xmlnode.getroot().remove(node)
                continue
            
            for o in arr:
                o.save()
                if o.xmlnode not in node:
                    node.append(o.xmlnode)
            xmlnodes = [o.xmlnode for o in arr]
            for n in node:
                if n not in xmlnodes:
                    node.remove(n)

        scenenode = self.xmlnode.find( tag('scene') )
        scenenode.clear()
        if self.scene is not None:
            sceneid = self.scene.id
            if sceneid not in self.scenes:
                raise DaeBrokenRefError('Default scene %s not found'%sceneid)
            scenenode.append(E.instance_visual_scene(url="#%s"%sceneid))
            
        if self.validator is not None:
            if not self.validator.validate(self.xmlnode):
                raise DaeSaveValidationError("Validation error when saving: " + 
                                             schema.COLLADA_SCHEMA_1_4_1_INSTANCE.error_log.last_error.message)

    def write(self, file):
        """Writes out the collada document to a file. Note that this also
        calls :meth:`save` so avoid calling both methods to save performance.
        
        :param file:
          Either the file name to write to or a file-like object
        
        """
        
        self.save()
        if type(file) in [types.StringType, types.UnicodeType]:
            f = open(file, 'w')
        else:
            f = file
            
        self.xmlnode.write(f, pretty_print=True)

    def __str__(self): return '<Collada geometries=%d>' % (len(self.geometries))
    def __repr__(self): return str(self)
    