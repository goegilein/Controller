import numpy as np
from PyQt6 import QtWidgets, QtGui, QtCore
from pyqtgraph.opengl import GLViewWidget,GLLinePlotItem
from OpenGL.GL import glDisable, GL_LIGHTING, glClearColor,glEnable, glBlendFunc, GL_BLEND, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA

class GCodePlotter():
    def __init__(self, gui, process_handler):
        self.gui = gui
        self.process_handler = process_handler
        self.plot_line_items = []

        self.plot_gcode_button = gui.plot_gcode_button
        self.gcode_canvas = gui.gcode_canvas
        self.plot_gcode_button.clicked.connect(self.plot_gcode)
        self.show_moves_checkBox = gui.show_moves_checkBox

        # Set up the PyQtGraph GLViewWidget for 3D plotting
        self.view = GLViewWidget()
        self.view.setBackgroundColor((255, 255, 255, 0))  # Set the background color to white
        #self.choose_background_color(QtGui.QColor(255, 255, 255))  # Set the initial background color to white
        self.view.opts['distance'] = 50  # Set the initial distance of the camera
        self.view.setCameraPosition(elevation=90, azimuth=-90)
        self.gcode_canvas.layout().addWidget(self.view)  # Add the GLViewWidget to the layout

        # Initialize OpenGL settings
        self.initializeGL()

    def plot_data(self):
        self.view.clear()
        for line_item in self.plot_line_items:
            line_item.setGLOptions("opaque")
            self.view.addItem(line_item)
    
    def add_data_to_plot_items(self, command_list, show_moves=True):
        pos, colors = self.extract_gcode_positions_and_colors(command_list, show_moves)
        # Create a line item for the current hatch line and add it to the view
        line_item = GLLinePlotItem(pos=pos, color=colors, width=2, mode='line_strip')
        self.plot_line_items.append(line_item)
    
    def plot_gcode(self):
        self.plot_line_items = []
        show_moves = self.show_moves_checkBox.isChecked()
        for step in self.process_handler.process_step_list:
                command_list=step.command_list
                self.add_data_to_plot_items(command_list, show_moves)
        self.plot_data()

    def extract_gcode_positions_and_colors(self, command_list, show_moves = True):
        positions = []
        colors = []
        x = y = z = 0.0
        prev_command=0
        if show_moves:
            g0_color = [0.7,0.7,0.7,0.5]
        else:
            g0_color = [1,1,1,0]
        g1_color = [0,0,0,1]

        for command in command_list:
            command = command.strip().upper()
            if command.startswith(("G0", "G1")):

                #detect switch between move and write depending on previous command
                if command.startswith("G0") and prev_command==1:
                    colors.append(g1_color)
                    positions.append([x, y, z])
                    colors.append(g0_color)
                    positions.append([x, y, z])
                    
                elif command.startswith("G1") and prev_command==0:
                    colors.append(g0_color)
                    positions.append([x, y, z])
                    colors.append(g1_color)
                    positions.append([x, y, z])

                # get the new point
                for token in command.split():
                    if token.startswith("X"):
                        x = float(token[1:])
                    elif token.startswith("Y"):
                        y = float(token[1:])
                    elif token.startswith("Z"):
                        z = float(token[1:])
                
                
                
                if command.startswith("G0"): 
                    colors.append(g0_color)
                    positions.append([x, y, z])
                    prev_command=0
                else:  # G1
                    colors.append(g1_color)
                    positions.append([x, y, z])
                    prev_command=1
        
        return np.array(positions), np.array(colors)

    def initializeGL(self):
        """
        Enable blending and disable lighting for consistent line colors.
        """
        glClearColor(1.0, 1.0, 1.0, 1.0)
        glEnable(GL_BLEND)  # Enable blending
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)  # Set blending function
        glDisable(GL_LIGHTING)  # Disable lighting effects