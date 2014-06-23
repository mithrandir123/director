import ddapp.objectmodel as om
import ddapp.applogic as app
from ddapp import affordance
from shallowCopy import shallowCopy
import ddapp.vtkAll as vtk
from ddapp.timercallback import TimerCallback
from ddapp import transformUtils
from ddapp import callbacks
import numpy as np
from PythonQt import QtCore, QtGui

from ddapp.affordancelistener import listener as affListener

import os
import weakref
import itertools

def computeAToB(a,b):

    t = vtk.vtkTransform()
    t.PostMultiply()
    t.Concatenate(b)
    t.Concatenate(a.GetLinearInverse())
    tt = vtk.vtkTransform()
    tt.SetMatrix(t.GetMatrix())
    return tt



class PolyDataItem(om.ObjectModelItem):

    def __init__(self, name, polyData, view):

        om.ObjectModelItem.__init__(self, name, om.Icons.Robot)

        self.views = []
        self.polyData = polyData
        self.mapper = vtk.vtkPolyDataMapper()
        self.mapper.SetInput(self.polyData)
        self.actor = vtk.vtkActor()
        self.actor.SetMapper(self.mapper)

        self.addProperty('Visible', True)
        self.addProperty('Point Size', self.actor.GetProperty().GetPointSize(),
                         attributes=om.PropertyAttributes(decimals=0, minimum=1, maximum=20, singleStep=1, hidden=False))
        self.addProperty('Alpha', 1.0,
                         attributes=om.PropertyAttributes(decimals=2, minimum=0, maximum=1.0, singleStep=0.1, hidden=False))
        self.addProperty('Color', QtGui.QColor(255,255,255))

        if view is not None:
            self.addToView(view)

    def _renderAllViews(self):
        for view in self.views:
            view.render()

    def hasDataSet(self, dataSet):
        return dataSet == self.polyData

    def setPolyData(self, polyData):

        arrayName = self.getColorByArrayName()

        self.polyData = polyData
        self.mapper.SetInput(polyData)
        self.colorBy(arrayName, lut=self.mapper.GetLookupTable())

        if self.getProperty('Visible'):
            self._renderAllViews()

    def getColorByArrayName(self):
        if self.polyData:
            scalars = self.polyData.GetPointData().GetScalars()
            if scalars:
                return scalars.GetName()

    def getArrayNames(self):
        pointData = self.polyData.GetPointData()
        return [pointData.GetArrayName(i) for i in xrange(pointData.GetNumberOfArrays())]

    def setSolidColor(self, color):

        color = [component * 255 for component in color]
        self.setProperty('Color', QtGui.QColor(*color))
        self.colorBy(None)

    def colorBy(self, arrayName, scalarRange=None, lut=None):

        if not arrayName:
            self.mapper.ScalarVisibilityOff()
            self.polyData.GetPointData().SetActiveScalars(None)
            return

        array = self.polyData.GetPointData().GetArray(arrayName)
        if not array:
            print 'colorBy(%s): array not found' % arrayName
            self.mapper.ScalarVisibilityOff()
            self.polyData.GetPointData().SetActiveScalars(None)
            return

        self.polyData.GetPointData().SetActiveScalars(arrayName)


        if not lut:
            if scalarRange is None:
                scalarRange = array.GetRange()

            lut = vtk.vtkLookupTable()
            lut.SetNumberOfColors(256)
            lut.SetHueRange(0.667, 0)
            lut.SetRange(scalarRange)
            lut.Build()


        #self.mapper.SetColorModeToMapScalars()
        self.mapper.ScalarVisibilityOn()
        self.mapper.SetUseLookupTableScalarRange(True)
        self.mapper.SetLookupTable(lut)
        self.mapper.InterpolateScalarsBeforeMappingOff()

        if self.getProperty('Visible'):
            self._renderAllViews()

    def getChildFrame(self):
        frameName = self.getProperty('Name') + ' frame'
        return self.findChild(frameName)

    def addToView(self, view):
        if view in self.views:
            return

        self.views.append(view)
        view.renderer().AddActor(self.actor)
        view.render()

    def _onPropertyChanged(self, propertySet, propertyName):
        om.ObjectModelItem._onPropertyChanged(self, propertySet, propertyName)

        if propertyName == 'Point Size':
            self.actor.GetProperty().SetPointSize(self.getProperty(propertyName))
        elif propertyName == 'Alpha':
            self.actor.GetProperty().SetOpacity(self.getProperty(propertyName))
        elif propertyName == 'Visible':
            self.actor.SetVisibility(self.getProperty(propertyName))
        elif propertyName == 'Color':
            color = self.getProperty(propertyName)
            color = [color.red()/255.0, color.green()/255.0, color.blue()/255.0]
            self.actor.GetProperty().SetColor(color)

        self._renderAllViews()

    def onRemoveFromObjectModel(self):
        self.removeFromAllViews()

    def removeFromAllViews(self):
        for view in list(self.views):
            self.removeFromView(view)
        assert len(self.views) == 0

    def removeFromView(self, view):
        assert view in self.views
        self.views.remove(view)
        view.renderer().RemoveActor(self.actor)
        view.render()


class AffordanceItem(PolyDataItem):

    def __init__(self, name, polyData, view):
        PolyDataItem.__init__(self, name, polyData, view)
        self.params = {}
        affListener.registerAffordance(self)
        self.addProperty('uid', 0, attributes=om.PropertyAttributes(decimals=0, minimum=0, maximum=1e6, singleStep=1, hidden=False))
        self.addProperty('Server updates enabled', False)

    def publish(self):
        pass

    def getActionNames(self):
        actions = ['Publish affordance']
        return PolyDataItem.getActionNames(self) + actions

    def onAction(self, action):
        if action == 'Publish affordance':
            self.publish()
        else:
            PolyDataItem.onAction(self, action)

    def onServerAffordanceUpdate(self, serverAff):
        if not self.params.get('uid'):
            self.params['uid'] = serverAff.uid
            self.setProperty('uid', serverAff.uid)

        if self.getProperty('Server updates enabled'):
            quat = transformUtils.botpy.roll_pitch_yaw_to_quat(serverAff.origin_rpy)
            t = transformUtils.transformFromPose(serverAff.origin_xyz, quat)
            self.actor.GetUserTransform().SetMatrix(t.GetMatrix())

    def onRemoveFromObjectModel(self):
        PolyDataItem.onRemoveFromObjectModel(self)
        affListener.unregisterAffordance(self)



class BlockAffordanceItem(AffordanceItem):

    def setAffordanceParams(self, params):
        self.params = params

    def updateParamsFromActorTransform(self):

        t = self.actor.GetUserTransform()

        xaxis = np.array(t.TransformVector([1,0,0]))
        yaxis = np.array(t.TransformVector([0,1,0]))
        zaxis = np.array(t.TransformVector([0,0,1]))
        self.params['xaxis'] = xaxis
        self.params['yaxis'] = yaxis
        self.params['zaxis'] = zaxis
        self.params['origin'] = t.GetPosition()


    def publish(self):
        self.updateParamsFromActorTransform()
        aff = affordance.createBoxAffordance(self.params)
        affordance.publishAffordance(aff)

        if hasattr(self, 'publishCallback'):
            self.publishCallback()

    def updateICPTransform(self, transform):
        delta = computeAToB(self.icpTransformInitial, transform)
        print 'initial:', self.icpTransformInitial.GetPosition(), self.icpTransformInitial.GetOrientation()
        print 'latest:', transform.GetPosition(), transform.GetOrientation()
        print 'delta:', delta.GetPosition(), delta.GetOrientation()
        newUserTransform = vtk.vtkTransform()
        newUserTransform.PostMultiply()
        newUserTransform.Identity()
        newUserTransform.Concatenate(self.baseTransform)
        newUserTransform.Concatenate(delta.GetLinearInverse())

        self.actor.SetUserTransform(newUserTransform)
        self._renderAllViews()


class FrameAffordanceItem(AffordanceItem):

    def setAffordanceParams(self, params):
        self.params = params
        assert 'otdf_type' in params

    def updateParamsFromActorTransform(self):

        t = self.actor.GetUserTransform()

        xaxis = np.array(t.TransformVector([1,0,0]))
        yaxis = np.array(t.TransformVector([0,1,0]))
        zaxis = np.array(t.TransformVector([0,0,1]))
        self.params['xaxis'] = xaxis
        self.params['yaxis'] = yaxis
        self.params['zaxis'] = zaxis
        self.params['origin'] = t.GetPosition()


    def publish(self):
        self.updateParamsFromActorTransform()
        aff = affordance.createFrameAffordance(self.params)
        affordance.publishAffordance(aff)


class CylinderAffordanceItem(AffordanceItem):

    def setAffordanceParams(self, params):
        self.params = params

    def updateParamsFromActorTransform(self):

        t = self.actor.GetUserTransform()

        xaxis = np.array(t.TransformVector([1,0,0]))
        yaxis = np.array(t.TransformVector([0,1,0]))
        zaxis = np.array(t.TransformVector([0,0,1]))
        self.params['axis'] = zaxis
        self.params['origin'] = t.GetPosition()


    def publish(self):
        self.updateParamsFromActorTransform()
        aff = affordance.createCylinderAffordance(self.params)
        affordance.publishAffordance(aff)


class FrameItem(PolyDataItem):

    def __init__(self, name, transform, view):

        scale = 1.0
        self.transform = transform
        polyData = self._createAxes(scale)

        PolyDataItem.__init__(self, name, polyData, view)

        self.colorBy('Axes')
        lut = self.mapper.GetLookupTable()
        lut.SetHueRange(0, 0.667)
        lut.Build()

        self._blockSignals = False

        self.actor.SetUserTransform(transform)

        self.widget = vtk.vtkFrameWidget()
        self.widget.CreateDefaultRepresentation()
        self.widget.EnabledOff()
        self.rep = self.widget.GetRepresentation()
        self.rep.SetWorldSize(scale)
        self.rep.SetTransform(transform)

        self.addProperty('Scale', scale, attributes=om.PropertyAttributes(decimals=2, minimum=0.01, maximum=100, singleStep=0.1, hidden=False))
        self.addProperty('Edit', False)

        self.callbacks = callbacks.CallbackRegistry(['FrameModified'])
        self.onTransformModifiedCallback = None
        self.observerTag = self.transform.AddObserver('ModifiedEvent', self.onTransformModified)

    def connectFrameModified(self, func):
        return self.callbacks.connect('FrameModified', func)

    def disconnectFrameModified(self, callbackId):
        self.callbacks.disconnect(callbackId)

    def onTransformModified(self, transform, event):
        if not self._blockSignals:
            if self.onTransformModifiedCallback:
                self.onTransformModifiedCallback(self)
            self.callbacks.process('FrameModified', self)

    def _createAxes(self, scale):
        axes = vtk.vtkAxes()
        axes.SetComputeNormals(0)
        axes.SetScaleFactor(scale)
        axes.Update()

        #t = vtk.vtkTransformPolyDataFilter()
        #t.SetTransform(transform)
        #t.AddInputConnection(self.axes.GetOutputPort())
        #t.Update()

        return shallowCopy(axes.GetOutput())

    def addToView(self, view):
        PolyDataItem.addToView(self, view)

    def copyFrame(self, transform):
        self._blockSignals = True
        self.transform.SetMatrix(transform.GetMatrix())
        self._blockSignals = False
        self.transform.Modified()
        if self.getProperty('Visible'):
            self._renderAllViews()

    def _onPropertyChanged(self, propertySet, propertyName):
        PolyDataItem._onPropertyChanged(self, propertySet, propertyName)

        if propertyName == 'Scale':
            scale = self.getProperty(propertyName)
            self.rep.SetWorldSize(scale)
            self.setPolyData(self._createAxes(scale))
        elif propertyName == 'Edit':
            view = app.getCurrentRenderView()
            if view not in self.views:
                view = self.views[0]
            self.widget.SetInteractor(view.renderWindow().GetInteractor())
            self.widget.SetEnabled(self.getProperty(propertyName))

    def onRemoveFromObjectModel(self):
        PolyDataItem.onRemoveFromObjectModel(self)

        self.transform.RemoveObserver(self.observerTag)

        self.widget.SetInteractor(None)
        self.widget.EnabledOff()
        for view in self.views:
            view.renderer().RemoveActor(self.actor)
            view.render()




class FrameSync(object):

    class FrameData(object):
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    def __init__(self):
        self.frames = {}
        self._blockCallbacks = False
        self._ids = itertools.count()

    def addFrame(self, frame, ignoreIncoming=False):

        if frame is None:
            return

        if self._findFrameId(frame) is not None:
            return

        frameId = self._ids.next()
        callbackId = frame.connectFrameModified(self._onFrameModified)

        self.frames[frameId] = FrameSync.FrameData(
            ref=weakref.ref(frame),
            baseTransform=self._computeBaseTransform(frame),
            callbackId=callbackId,
            ignoreIncoming=ignoreIncoming)

    def removeFrame(self, frame):

        frameId = self._findFrameId(frame)
        if frameId is None:
            raise KeyError(frame)

        frame.disconnectFrameModified(self.frames[frameId].callbackId)
        self._removeFrameId(frameId)

    def _computeBaseTransform(self, frame):

        currentDelta = None
        for frameId, frameData in self.frames.items():

            if frameData.ref() is None:
                self._removeFrameId(frameId)
            elif frameData.ref() is frame:
                continue
            else:
                currentDelta = transformUtils.copyFrame(frameData.baseTransform.GetLinearInverse())
                currentDelta.Concatenate(transformUtils.copyFrame(frameData.ref().transform))
                break

        t = transformUtils.copyFrame(frame.transform)
        t.PostMultiply()
        if currentDelta:
            t.Concatenate(currentDelta.GetLinearInverse())

        return t

    def _removeFrameId(self, frameId):
        del self.frames[frameId]

    def _findFrameId(self, frame):

        for frameId, frameData in self.frames.items():

            if frameData.ref() is None:
                self._removeFrameId(frameId)
            elif frameData.ref() is frame:
                return frameId

    def _moveFrame(self, frameId, modifiedFrameId):

        frameData = self.frames[frameId]
        modifiedFrameData = self.frames[modifiedFrameId]

        t = vtk.vtkTransform()
        t.PostMultiply()
        t.Concatenate(frameData.baseTransform)
        t.Concatenate(modifiedFrameData.baseTransform.GetLinearInverse())
        t.Concatenate(modifiedFrameData.ref().transform)
        frameData.ref().copyFrame(t)

    def _onFrameModified(self, frame):

        if self._blockCallbacks:
            return

        modifiedFrameId = self._findFrameId(frame)
        assert modifiedFrameId is not None

        #print self, 'onFrameModified:', self.frames[modifiedFrameId].ref().getProperty('Name')

        if self.frames[modifiedFrameId].ignoreIncoming:
            self.frames[modifiedFrameId].baseTransform = self._computeBaseTransform(frame)
            return

        self._blockCallbacks = True

        for frameId, frameData in self.frames.items():
            if frameData.ref() is None:
                self._removeFrameId(frameId)
            elif frameId != modifiedFrameId:

                #print '  ', self, 'moving:', self.frames[frameId].ref().getProperty('Name')
                self._moveFrame(frameId, modifiedFrameId)

        self._blockCallbacks = False



def showGrid(view, cellSize=0.5, numberOfCells=25, name='grid', parent='sensors', color=None):

    grid = vtk.vtkGridSource()
    grid.SetScale(cellSize)
    grid.SetGridSize(numberOfCells)
    grid.Update()
    #color = [0.33,0.66,0]
    color = color or [1, 1, 1]
    gridObj = showPolyData(grid.GetOutput(), 'grid', view=view, alpha=0.10, color=color, visible=True, parent=parent)
    gridObj.gridSource = grid
    gridObj.actor.GetProperty().LightingOff()
    gridObj.actor.SetPickable(False)

    def computeViewBoundsNoGrid():
        if not gridObj.getProperty('Visible'):
            return

        gridObj.actor.SetUseBounds(False)
        bounds = view.renderer().ComputeVisiblePropBounds()
        gridObj.actor.SetUseBounds(True)
        if vtk.vtkMath.AreBoundsInitialized(bounds):
            view.addCustomBounds(bounds)
        else:
            view.addCustomBounds([-1, 1, -1, 1, -1, 1])

    view.connect('computeBoundsRequest(ddQVTKWidgetView*)', computeViewBoundsNoGrid)

    return gridObj


def createScalarBarWidget(view, lookupTable, title):

    w = vtk.vtkScalarBarWidget()
    bar = w.GetScalarBarActor()
    bar.SetTitle(title)
    bar.SetLookupTable(lookupTable)
    w.SetRepositionable(True)
    w.SetInteractor(view.renderWindow().GetInteractor())
    w.On()

    rep = w.GetRepresentation()
    rep.SetOrientation(0)
    rep.SetPosition(0.77, 0.92)
    rep.SetPosition2(0.20, 0.07)

    return w


def updatePolyData(polyData, name, **kwargs):

    obj = om.findObjectByName(name)
    obj = obj or showPolyData(polyData, name, **kwargs)
    obj.setPolyData(polyData)
    return obj


def updateFrame(frame, name, **kwargs):

    obj = om.findObjectByName(name)
    obj = obj or showFrame(frame, name, **kwargs)
    obj.copyFrame(frame)
    return obj


def showFrame(frame, name, view=None, parent='segmentation', scale=0.35, visible=True):

    view = view or app.getCurrentRenderView()
    assert view

    if isinstance(parent, str):
        parentObj = om.getOrCreateContainer(parent)
    else:
        parentObj = parent

    item = FrameItem(name, frame, view)
    om.addToObjectModel(item, parentObj)
    item.setProperty('Visible', visible)
    item.setProperty('Scale', scale)
    return item


def showPolyData(polyData, name, color=None, colorByName=None, colorByRange=None, alpha=1.0, visible=True, view=None, parent='segmentation', cls=None):

    view = view or app.getCurrentRenderView()
    assert view

    cls = cls or PolyDataItem
    item = cls(name, polyData, view)

    if isinstance(parent, str):
        parentObj = om.getOrCreateContainer(parent)
    else:
        parentObj = parent

    om.addToObjectModel(item, parentObj)
    item.setProperty('Visible', visible)
    item.setProperty('Alpha', alpha)
    if color:
        color = [component * 255 for component in color]
        item.setProperty('Color', QtGui.QColor(*color))
        item.colorBy(None)
    else:
        item.colorBy(colorByName, colorByRange)
    return item


def showHandCloud(hand='left', view=None):

    view = view or app.getCurrentRenderView()
    if view is None:
        return

    assert hand in ('left', 'right')

    maps = om.findObjectByName('Map Server')
    assert maps is not None

    viewId = 52 if hand == 'left' else 53
    reader = maps.source.reader

    def getCurrentViewId():
        return reader.GetCurrentMapId(viewId)

    p = vtk.vtkPolyData()
    obj = showPolyData(p, '%s hand cloud' % hand, view=view, parent='sensors')
    obj.currentViewId = -1

    def updateCloud():
        currentViewId = getCurrentViewId()
        #print 'updateCloud: current view id:', currentViewId
        if currentViewId != obj.currentViewId:
            reader.GetDataForMapId(viewId, currentViewId, p)
            #print 'updated poly data.  %d points.' % p.GetNumberOfPoints()
            obj._renderAllViews()

    t = TimerCallback()
    t.targetFps = 1
    t.callback = updateCloud
    t.start()
    obj.updater = t
    return obj


def showClusterObjects(clusters, parent):

    colors =  [ QtCore.Qt.red,
                QtCore.Qt.blue,
                QtCore.Qt.yellow,
                QtCore.Qt.magenta,
                QtCore.Qt.cyan,
                QtCore.Qt.green,
                QtCore.Qt.darkCyan,
                QtCore.Qt.darkGreen,
                QtCore.Qt.darkMagenta ]

    colors = [QtGui.QColor(c) for c in colors]
    colors = [(c.red()/255.0, c.green()/255.0, c.blue()/255.0) for c in colors]

    objects = []

    for i, cluster in enumerate(clusters):
        name = 'object %d' % i
        color = colors[i % len(colors)]
        clusterObj = showPolyData(cluster.mesh, name, color=color, parent=parent, alpha=0.25)
        clusterFrame = showFrame(cluster.frame, name + ' frame', scale=0.2, visible=False, parent=clusterObj)
        clusterObj.actor.GetProperty().EdgeVisibilityOn()
        clusterBox = showPolyData(cluster.box, name + ' box', color=color, parent=clusterObj, alpha=0.6)
        clusterPoints = showPolyData(cluster.points, name + ' points', color=color, parent=clusterObj, visible=True, alpha=1.0)
        clusterPoints.setProperty('Point Size', 7)
        clusterPoints.colorBy(None)
        objects.append(clusterObj)

        for obj in [clusterObj, clusterBox, clusterPoints]:
            obj.actor.SetUserTransform(cluster.frame)

    return objects


captionWidget = None

def hideCaptionWidget():
    global captionWidget
    if captionWidget is not None:
        captionWidget.Off()
        captionWidget.Render()


def showCaptionWidget(position, text, view=None):

    view = view or app.getCurrentRenderView()
    assert view

    global captionWidget

    if not captionWidget:
        rep = vtk.vtkCaptionRepresentation()
        rep.SetPosition(0.2, 0.8)
        w = vtk.vtkCaptionWidget()
        w.SetInteractor(view.renderWindow().GetInteractor())
        w.SetRepresentation(rep)
        w.On()
        captionWidget = w

    rep = captionWidget.GetRepresentation()
    rep.SetAnchorPosition(position)
    rep.GetCaptionActor2D().SetCaption(text)

    a = rep.GetCaptionActor2D()

    pr = a.GetTextActor().GetTextProperty()
    pr.SetJustificationToCentered()
    pr.SetVerticalJustificationToCentered()
    pr.SetItalic(0)
    pr.SetBold(0)
    pr.SetShadow(0)
    pr.SetFontFamilyToArial()

    c2 = rep.GetPosition2Coordinate()
    c2.SetCoordinateSystemToDisplay()
    c2.SetValue(12*len(text),30)

    # disable border
    #rep.SetShowBorder(0)

    a.SetThreeDimensionalLeader(0)
    a.SetLeaderGlyphSize(0.005)

    captionWidget.On()
    captionWidget.Render()


def pickImage(displayPoint, view, obj=None):

    picker = vtk.vtkCellPicker()

    if isinstance(obj, str):
        obj = om.findObjectByName(obj)
        assert obj

    if obj:
        picker.AddPickList(obj.actor)
        picker.PickFromListOn()

    picker.Pick(displayPoint[0], displayPoint[1], 0, view.renderer())
    pickedDataset = picker.GetDataSet()

    if obj:
        return picker.GetPointIJK()
    else:
        return pickedDataset, picker.GetPointIJK()


def pickProp(displayPoint, view):

    for tolerance in (0.0, 0.005, 0.01):
        pickType = 'render' if tolerance == 0.0 else 'cells'
        pickedPoint, pickedProp, pickedDataset = pickPoint(displayPoint, view, pickType=pickType, tolerance=tolerance)
        if pickedProp is not None:
            return pickedPoint, pickedProp, pickedDataset

    return None, None, None


def pickPoint(displayPoint, view, obj=None, pickType='points', tolerance=0.01, returnNormal=False):

    assert pickType in ('points', 'cells', 'render')

    view = view or app.getCurrentRenderView()
    assert view

    if isinstance(obj, str):
        obj = om.findObjectByName(obj)
        assert obj


    if pickType == 'render':
        picker = vtk.vtkPropPicker()
    else:
        picker = vtk.vtkPointPicker() if pickType == 'points' else vtk.vtkCellPicker()
        picker.SetTolerance(tolerance)


    if obj:
        if isinstance(obj, list):
            for o in obj:
                picker.AddPickList(o.actor)
            obj = None
        else:
            picker.AddPickList(obj.actor)
        picker.PickFromListOn()

    picker.Pick(displayPoint[0], displayPoint[1], 0, view.renderer())
    pickedProp = picker.GetViewProp()
    pickedPoint = np.array(picker.GetPickPosition())
    pickedDataset = pickedProp.GetMapper().GetInput() if isinstance(pickedProp, vtk.vtkActor) else None

    pickedNormal = np.zeros(3)

    if returnNormal:
        if pickType == 'cells':
          pickedNormal = np.array(picker.GetPickNormal())
        elif pickType == 'points' and pickedDataset:
          pointId = picker.GetPointId()
          normals = pickedDataset.GetPointData().GetNormals()
          if normals:
              pickedNormal = np.array(normals.GetTuple3(pointId))


    if obj:
        if returnNormal:
            return (pickedPoint, pickedNormal) if pickedProp else (None, None)
        else:
            return pickedPoint if pickedProp else None
    else:
        return (pickedPoint, pickedProp, pickedDataset, pickedNormal) if returnNormal else (pickedPoint, pickedProp, pickedDataset)


def mapMousePosition(widget, mouseEvent):
    mousePosition = mouseEvent.pos()
    return mousePosition.x(), widget.height - mousePosition.y()


def getObjectByDataSet(polyData):
    for obj in om.getObjects():
        if obj.hasDataSet(polyData):
            return obj

def getObjectByProp(prop):
    if not prop:
        return None
    for obj in om.getObjects():
        if isinstance(obj, FrameItem) and obj.widget.GetRepresentation() == prop:
            return obj
    if isinstance(prop, vtk.vtkActor):
        return getObjectByDataSet(prop.GetMapper().GetInput())


def findPickedObject(displayPoint, view):

    pickedPoint, pickedProp, pickedDataset = pickProp(displayPoint, view)
    obj = getObjectByProp(pickedProp)
    return obj, pickedPoint


def showImage(filename):
    '''
    Returns a QLabel displaying the image contents of given filename.
    Make sure to assign the label, it will destruct when it goes out
    of scope.
    '''
    image = QtGui.QImage(filename)
    assert not image.isNull()
    imageLabel = QtGui.QLabel()
    imageLabel.setPixmap(QtGui.QPixmap.fromImage(image))
    imageLabel.setScaledContents(True)
    imageLabel.resize(imageLabel.pixmap.size())
    imageLabel.setWindowTitle(os.path.basename(filename))
    imageLabel.show()
